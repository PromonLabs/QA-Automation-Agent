"""
CPU fine-tuning — Qwen2.5-0.5B — uses transformers.Trainer directly (no TRL version issues)
"""
import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model, TaskType
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
    DataCollatorForLanguageModeling,
    EarlyStoppingCallback,
)

MODEL_ID   = "Qwen/Qwen2.5-0.5B-Instruct"
OUTPUT_DIR = "./output"
DATA_DIR   = "./data"
MAX_LEN    = 1024

print("Step 1/5 — Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
tokenizer.padding_side = "right"
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

print("Step 2/5 — Loading model on CPU...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.float32,
    device_map="cpu",
    trust_remote_code=True,
)
model.config.use_cache = False

lora_config = LoraConfig(
    task_type      = TaskType.CAUSAL_LM,
    r              = 8,
    lora_alpha     = 16,
    lora_dropout   = 0.1,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj"],
    bias           = "none",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

print("Step 3/5 — Loading dataset...")
ds = load_dataset("json", data_files={
    "train":      f"{DATA_DIR}/train.jsonl",
    "validation": f"{DATA_DIR}/val.jsonl",
})
print(f"  Train: {len(ds['train'])} examples   Val: {len(ds['validation'])} examples")

def tokenize(example):
    text = tokenizer.apply_chat_template(
        example["messages"], tokenize=False, add_generation_prompt=False
    )
    out = tokenizer(text, truncation=True, max_length=MAX_LEN, padding="max_length")
    out["labels"] = out["input_ids"].copy()
    return out

print("Step 4/5 — Tokenizing...")
ds = ds.map(tokenize, remove_columns=ds["train"].column_names)
ds.set_format("torch")

print("Step 5/5 — Setting up trainer...")
args = TrainingArguments(
    output_dir                  = OUTPUT_DIR,
    num_train_epochs            = 15,
    per_device_train_batch_size = 1,
    per_device_eval_batch_size  = 1,
    gradient_accumulation_steps = 4,
    learning_rate               = 2e-4,
    weight_decay                = 0.01,
    lr_scheduler_type           = "cosine",
    warmup_steps                = 5,
    max_grad_norm               = 0.3,
    fp16                        = False,
    bf16                        = False,
    optim                       = "adamw_torch",
    logging_steps               = 1,
    eval_strategy               = "steps",
    eval_steps                  = 10,
    save_strategy               = "steps",
    save_steps                  = 10,
    save_total_limit            = 3,
    load_best_model_at_end      = True,
    metric_for_best_model       = "eval_loss",
    greater_is_better           = False,
    report_to                   = "none",
    seed                        = 42,
    dataloader_num_workers      = 0,
    use_cpu                     = True,
)

trainer = Trainer(
    model         = model,
    args          = args,
    train_dataset = ds["train"],
    eval_dataset  = ds["validation"],
    data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    callbacks     = [EarlyStoppingCallback(early_stopping_patience=5)],
)

print("\n" + "="*50)
print(" Training started! Watch loss drop each epoch.")
print(" Lower loss = model is learning your flows.")
print("="*50 + "\n")

trainer.train()

adapter_path = f"{OUTPUT_DIR}/lora_adapter"
trainer.model.save_pretrained(adapter_path)
tokenizer.save_pretrained(adapter_path)
print(f"\nDone! Adapter saved -> {adapter_path}")
