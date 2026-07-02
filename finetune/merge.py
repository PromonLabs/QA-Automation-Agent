"""Merge LoRA adapter into base model and save as HuggingFace format."""
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL   = "Qwen/Qwen2.5-0.5B-Instruct"
ADAPTER_PATH = "./output/lora_adapter"
OUTPUT_PATH  = "./output/merged"

print("Loading base model...")
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL, torch_dtype=torch.float32, device_map="cpu", trust_remote_code=True
)
print("Loading LoRA adapter...")
model = PeftModel.from_pretrained(model, ADAPTER_PATH)

print("Merging weights...")
model = model.merge_and_unload()

print(f"Saving merged model -> {OUTPUT_PATH}")
model.save_pretrained(OUTPUT_PATH, safe_serialization=True)

tokenizer = AutoTokenizer.from_pretrained(ADAPTER_PATH, trust_remote_code=True)
tokenizer.save_pretrained(OUTPUT_PATH)

print("Done! Merged model saved.")
