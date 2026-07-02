"""
finetune.py
===========
QLoRA fine-tuning for browser automation workflow generation.

Supports: Qwen2.5-7B-Instruct (recommended), Llama-3.1-8B-Instruct, Mistral-7B-Instruct-v0.3

Requirements:
  pip install torch transformers datasets peft trl bitsandbytes accelerate wandb

Hardware:
  - Minimum: 8 GB VRAM (RTX 3070/4060) — use load_in_4bit=True
  - Recommended: 16 GB VRAM (RTX 3080/4080) — use load_in_4bit=True or load_in_8bit=True
  - For 14B models: 24 GB+ VRAM (RTX 3090/4090)

Usage:
  python finetune.py --model qwen2.5-7b --data_dir ./data --output_dir ./output

  # Resume from checkpoint:
  python finetune.py --model qwen2.5-7b --data_dir ./data --output_dir ./output \
                     --resume_from_checkpoint ./output/checkpoint-100
"""

import argparse
import os
import math
from pathlib import Path

import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model, TaskType, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    EarlyStoppingCallback,
)
from trl import SFTTrainer, DataCollatorForCompletionOnlyLM


# ── Model registry ───────────────────────────────────────────────────────────
MODELS = {
    "qwen2.5-7b":    "Qwen/Qwen2.5-7B-Instruct",
    "qwen2.5-14b":   "Qwen/Qwen2.5-14B-Instruct",
    "llama3-8b":     "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "mistral-7b":    "mistralai/Mistral-7B-Instruct-v0.3",
}

# Target modules for LoRA (attention + FFN projections)
LORA_TARGETS = {
    "qwen2.5-7b":  ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "qwen2.5-14b": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "llama3-8b":   ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "mistral-7b":  ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model",        default="qwen2.5-7b", choices=list(MODELS))
    p.add_argument("--data_dir",     default="./data")
    p.add_argument("--output_dir",   default="./output")
    p.add_argument("--resume_from_checkpoint", default=None)

    # ── Training hyperparameters ──────────────────────────────────────────────
    # These are tuned for a 7B model with 4-bit quantization on 8–16 GB VRAM.
    # With <200 training examples: use 3–5 epochs.
    # With 1000+ examples:         use 1–3 epochs.
    p.add_argument("--num_epochs",        type=int,   default=3)
    p.add_argument("--batch_size",        type=int,   default=1)    # per-device
    p.add_argument("--grad_accum",        type=int,   default=8)    # effective batch = 8
    p.add_argument("--lr",                type=float, default=2e-4) # QLoRA sweet spot
    p.add_argument("--max_seq_len",       type=int,   default=2048) # covers all our flows
    p.add_argument("--warmup_ratio",      type=float, default=0.05)
    p.add_argument("--weight_decay",      type=float, default=0.01)
    p.add_argument("--lr_scheduler",      default="cosine")

    # ── LoRA parameters ───────────────────────────────────────────────────────
    # r=16: good for task-specific fine-tuning (increase to 32 for larger dataset)
    # alpha=32: keeps LoRA scale = alpha/r = 2 (standard)
    # dropout=0.1: regularization to prevent overfitting on small datasets
    p.add_argument("--lora_r",       type=int,   default=16)
    p.add_argument("--lora_alpha",   type=int,   default=32)
    p.add_argument("--lora_dropout", type=float, default=0.1)

    # ── Quantization ──────────────────────────────────────────────────────────
    p.add_argument("--load_in_4bit", action="store_true", default=True)
    p.add_argument("--load_in_8bit", action="store_true", default=False)

    # ── Evaluation & saving ───────────────────────────────────────────────────
    p.add_argument("--eval_steps",   type=int, default=50)
    p.add_argument("--save_steps",   type=int, default=50)
    p.add_argument("--logging_steps",type=int, default=10)

    return p.parse_args()


def build_bnb_config(args) -> BitsAndBytesConfig | None:
    if args.load_in_4bit:
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,   # saves ~0.4 bits/param extra
            bnb_4bit_quant_type="nf4",        # NormalFloat4 — best for LLM weights
        )
    if args.load_in_8bit:
        return BitsAndBytesConfig(load_in_8bit=True)
    return None


def format_chat(example: dict) -> str:
    """
    Apply the model's chat template to convert messages → a single string.
    SFTTrainer needs raw strings when not using a DataCollator.
    The tokenizer.apply_chat_template handles all model-specific formatting.
    """
    # This is called at dataset-map time, so tokenizer is a closure
    return format_chat._tokenizer.apply_chat_template(
        example["messages"],
        tokenize=False,
        add_generation_prompt=False,
    )


def main():
    args = parse_args()
    model_id     = MODELS[args.model]
    output_path  = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f" Model:      {model_id}")
    print(f" Epochs:     {args.num_epochs}")
    print(f" Batch:      {args.batch_size} × {args.grad_accum} grad accum = {args.batch_size * args.grad_accum} effective")
    print(f" LR:         {args.lr}")
    print(f" Max seq:    {args.max_seq_len} tokens")
    print(f" LoRA r:     {args.lora_r}  alpha: {args.lora_alpha}  dropout: {args.lora_dropout}")
    print(f" 4-bit:      {args.load_in_4bit}")
    print(f"{'='*60}\n")

    # ── Load tokenizer ────────────────────────────────────────────────────────
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    tokenizer.padding_side = "right"   # required for SFTTrainer
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    format_chat._tokenizer = tokenizer  # make accessible inside closure

    # ── Load dataset ──────────────────────────────────────────────────────────
    data_files = {
        "train": str(Path(args.data_dir) / "train.jsonl"),
        "validation": str(Path(args.data_dir) / "val.jsonl"),
    }
    ds = load_dataset("json", data_files=data_files)
    print(f"Dataset: {len(ds['train'])} train  /  {len(ds['validation'])} val examples")

    # Format each example as a single string using the model's chat template
    ds = ds.map(
        lambda ex: {"text": format_chat(ex)},
        remove_columns=ds["train"].column_names,
        desc="Applying chat template",
    )

    # ── Load model ────────────────────────────────────────────────────────────
    bnb_config = build_bnb_config(args)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=bnb_config,
        device_map="auto",             # spread across available GPUs/CPU
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        attn_implementation="flash_attention_2" if torch.cuda.is_available() else "eager",
    )
    model.config.use_cache = False     # required for gradient checkpointing
    model.config.pretraining_tp = 1

    if bnb_config:
        model = prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=True
        )

    # ── LoRA config ───────────────────────────────────────────────────────────
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=LORA_TARGETS[args.model],
        bias="none",
        # Only train the assistant's responses, not the prompt
        # (handled by DataCollatorForCompletionOnlyLM below)
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ── Training arguments ────────────────────────────────────────────────────
    training_args = TrainingArguments(
        output_dir=str(output_path),
        num_train_epochs=args.num_epochs,

        # Batch size
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,

        # Optimizer
        optim="paged_adamw_32bit",     # memory-efficient paged AdamW
        learning_rate=args.lr,
        weight_decay=args.weight_decay,
        lr_scheduler_type=args.lr_scheduler,
        warmup_ratio=args.warmup_ratio,
        max_grad_norm=0.3,             # clip large gradients (important for QLoRA)

        # Precision
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        gradient_checkpointing=True,   # trade speed for memory

        # Logging & checkpointing
        logging_dir=str(output_path / "logs"),
        logging_steps=args.logging_steps,
        evaluation_strategy="steps",
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=args.save_steps,
        save_total_limit=3,            # keep only last 3 checkpoints
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,

        # Misc
        report_to="none",              # set to "wandb" if you want tracking
        seed=42,
        dataloader_num_workers=0,      # 0 = main process (safe on Windows)
        remove_unused_columns=False,
    )

    # ── Trainer ───────────────────────────────────────────────────────────────
    # DataCollatorForCompletionOnlyLM ensures we only compute loss on
    # the ASSISTANT response tokens, not on the prompt/system tokens.
    # This is critical for correct instruction fine-tuning.
    response_template = "<|im_start|>assistant"   # Qwen / ChatML format
    if "llama" in args.model:
        response_template = "<|start_header_id|>assistant<|end_header_id|>"
    elif "mistral" in args.model:
        response_template = "[/INST]"

    collator = DataCollatorForCompletionOnlyLM(
        response_template=response_template,
        tokenizer=tokenizer,
        mlm=False,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=ds["train"],
        eval_dataset=ds["validation"],
        dataset_text_field="text",
        max_seq_length=args.max_seq_len,
        data_collator=collator,
        peft_config=lora_config,
        args=training_args,
        callbacks=[
            EarlyStoppingCallback(
                early_stopping_patience=5,    # stop if val loss doesn't improve for 5 evals
                early_stopping_threshold=0.001,
            )
        ],
    )

    # ── Train ─────────────────────────────────────────────────────────────────
    print("\nStarting training…")
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)

    # ── Save final LoRA adapter ───────────────────────────────────────────────
    adapter_path = output_path / "lora_adapter"
    trainer.model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))
    print(f"\nLoRA adapter saved → {adapter_path}")
    print("Next step: run export_model.py to merge weights and convert to GGUF for Ollama.")


if __name__ == "__main__":
    main()
