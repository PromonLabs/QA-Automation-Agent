# ============================================================
# QA Automation Agent — Fine-Tuning Notebook for Google Colab
# ============================================================
# 1. Go to https://colab.research.google.com
# 2. New notebook → Runtime → Change runtime type → T4 GPU
# 3. Paste each cell below and run in order
# ============================================================


# ── CELL 1: Install packages ─────────────────────────────────────────────────
"""
!pip install -q unsloth
!pip install -q xformers trl peft accelerate bitsandbytes
"""

# ── CELL 2: Upload your training data ────────────────────────────────────────
"""
# Upload train.jsonl and val.jsonl from your local machine:
from google.colab import files
uploaded = files.upload()   # select train.jsonl and val.jsonl
"""

# ── CELL 3: Load model with Unsloth (2x faster than standard QLoRA) ──────────
"""
from unsloth import FastLanguageModel
import torch

MODEL_NAME   = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"  # pre-quantized, downloads fast
MAX_SEQ_LEN  = 2048
LORA_R       = 16
OUTPUT_DIR   = "/content/output"

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name     = MODEL_NAME,
    max_seq_length = MAX_SEQ_LEN,
    dtype          = None,      # auto-detect bf16/fp16
    load_in_4bit   = True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r                = LORA_R,
    lora_alpha       = 32,
    lora_dropout     = 0.1,
    target_modules   = ["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    bias             = "none",
    use_gradient_checkpointing = "unsloth",  # saves more VRAM
    random_state     = 42,
)
print(model.print_trainable_parameters())
"""

# ── CELL 4: Load dataset ──────────────────────────────────────────────────────
"""
from datasets import load_dataset

ds = load_dataset("json", data_files={
    "train":      "train.jsonl",
    "validation": "val.jsonl",
})
print(f"Train: {len(ds['train'])}  Val: {len(ds['validation'])}")

def format_example(example):
    text = tokenizer.apply_chat_template(
        example["messages"],
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}

ds = ds.map(format_example, remove_columns=ds["train"].column_names)
print("Sample:", ds["train"][0]["text"][:300])
"""

# ── CELL 5: Train ─────────────────────────────────────────────────────────────
"""
from trl import SFTTrainer, DataCollatorForCompletionOnlyLM
from transformers import TrainingArguments, EarlyStoppingCallback
from unsloth import is_bfloat16_supported

response_template = "<|im_start|>assistant"

collator = DataCollatorForCompletionOnlyLM(
    response_template = response_template,
    tokenizer         = tokenizer,
    mlm               = False,
)

trainer = SFTTrainer(
    model             = model,
    tokenizer         = tokenizer,
    train_dataset     = ds["train"],
    eval_dataset      = ds["validation"],
    dataset_text_field= "text",
    max_seq_length    = MAX_SEQ_LEN,
    data_collator     = collator,
    args = TrainingArguments(
        output_dir                  = OUTPUT_DIR,
        num_train_epochs            = 15,
        per_device_train_batch_size = 2,
        per_device_eval_batch_size  = 1,
        gradient_accumulation_steps = 4,     # effective batch = 8
        learning_rate               = 2e-4,
        weight_decay                = 0.01,
        lr_scheduler_type           = "cosine",
        warmup_ratio                = 0.05,
        max_grad_norm               = 0.3,
        fp16                        = not is_bfloat16_supported(),
        bf16                        = is_bfloat16_supported(),
        gradient_checkpointing      = True,
        optim                       = "adamw_8bit",
        logging_steps               = 5,
        evaluation_strategy         = "steps",
        eval_steps                  = 10,
        save_strategy               = "steps",
        save_steps                  = 10,
        save_total_limit            = 3,
        load_best_model_at_end      = True,
        metric_for_best_model       = "eval_loss",
        greater_is_better           = False,
        report_to                   = "none",
        seed                        = 42,
    ),
    callbacks = [EarlyStoppingCallback(early_stopping_patience=5)],
)

print("Starting training...")
trainer.train()
print("Training complete!")
"""

# ── CELL 6: Quick test before saving ─────────────────────────────────────────
"""
FastLanguageModel.for_inference(model)

prompt = tokenizer.apply_chat_template([
    {"role": "system",  "content": "You are a browser automation expert. Output JSON only."},
    {"role": "user",    "content": (
        "Create a browser automation flow to top up a customer's talk credit. "
        "Use ${COS_URL}, ${PORTAL_URL}, ${PHONE_NUMBER}, ${TOPUP_AMOUNT}, "
        "${CARD_NUMBER}, ${CARD_MONTH}, ${CARD_YEAR}, ${CARD_CVV}."
    )},
], tokenize=False, add_generation_prompt=True)

inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
outputs = model.generate(
    **inputs,
    max_new_tokens = 1500,
    temperature    = 0.05,
    do_sample      = True,
    pad_token_id   = tokenizer.eos_token_id,
)
response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
print(response)
"""

# ── CELL 7: Save LoRA adapter ─────────────────────────────────────────────────
"""
adapter_path = "/content/output/lora_adapter"
model.save_pretrained(adapter_path)
tokenizer.save_pretrained(adapter_path)
print(f"LoRA adapter saved to {adapter_path}")
"""

# ── CELL 8: Convert to GGUF and download ─────────────────────────────────────
"""
# Merge and export to GGUF (q4_k_m) so you can use it with Ollama locally.
model.save_pretrained_gguf(
    "/content/output/automation-agent",
    tokenizer,
    quantization_method = "q4_k_m",
)

# Download the GGUF file to your local machine
from google.colab import files
import os, glob

gguf_files = glob.glob("/content/output/automation-agent*.gguf")
for f in gguf_files:
    print(f"Downloading {f} ({os.path.getsize(f)/1e9:.1f} GB)...")
    files.download(f)
"""

# ── CELL 9 (Local): Register with Ollama after download ──────────────────────
"""
# Run this on YOUR machine after downloading the .gguf file:

# 1. Create Modelfile (replace the path with your downloaded file):
MODELFILE = '''
FROM ./automation-agent-q4_k_m.gguf

SYSTEM """You are a browser automation expert. Generate browser automation flows as JSON.
Always output valid JSON with name and steps fields. Use ${VAR_NAME} for dynamic values.
Actions: navigate, click, type, select, wait, screenshot, extract, verify, press_key, scroll, report."""

PARAMETER temperature 0.05
PARAMETER top_p 0.9
PARAMETER num_predict 2000
PARAMETER num_ctx 4096
PARAMETER stop "<|im_end|>"
'''

with open("Modelfile", "w") as f:
    f.write(MODELFILE)

# 2. Register:
#    ollama create automation-agent -f Modelfile

# 3. Test:
#    ollama run automation-agent "Create a flow to top up customer ${PHONE_NUMBER}"

# 4. Use in your QA agent (backend/.env):
#    LLM_PROVIDER=ollama
#    LLM_MODEL=automation-agent
#    USE_FLOW_AGENT=true
"""
