"""
export_model.py
===============
Merge LoRA adapter into the base model, then convert to GGUF for Ollama.

Steps:
  1. Merge LoRA weights into base model  → ./output/merged/
  2. Convert merged model to GGUF        → ./output/automation-agent-q4.gguf
  3. Create Ollama Modelfile             → ./output/Modelfile
  4. Register with Ollama                → ollama create automation-agent

Usage:
  python export_model.py --model qwen2.5-7b \
                          --adapter_path ./output/lora_adapter \
                          --output_dir ./output \
                          --quantize q4_k_m
"""

import argparse
import subprocess
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


MODELS = {
    "qwen2.5-7b":  "Qwen/Qwen2.5-7B-Instruct",
    "qwen2.5-14b": "Qwen/Qwen2.5-14B-Instruct",
    "llama3-8b":   "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "mistral-7b":  "mistralai/Mistral-7B-Instruct-v0.3",
}

SYSTEM_PROMPT = """You are a browser automation expert. You understand web UI automation workflows
written as ordered JSON step lists. You can:
- Generate new automation flows from natural language descriptions
- Explain what a flow does and what variables it uses
- Extend existing flows with new steps
- Identify variables and their purpose
- Convert between natural language and structured JSON automation steps

Always produce valid JSON when asked for a flow. Use ${VAR_NAME} syntax for dynamic values.
Available actions: navigate, click, type, select, wait, screenshot, extract, verify, press_key, scroll, report."""


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model",         default="qwen2.5-7b", choices=list(MODELS))
    p.add_argument("--adapter_path",  default="./output/lora_adapter")
    p.add_argument("--output_dir",    default="./output")
    p.add_argument("--quantize",      default="q4_k_m",
                   choices=["q4_k_m", "q5_k_m", "q8_0", "f16"],
                   help="GGUF quantization level. q4_k_m = best quality/size ratio.")
    p.add_argument("--ollama_name",   default="automation-agent")
    p.add_argument("--llama_cpp_dir", default="./llama.cpp",
                   help="Path to llama.cpp repo (cloned for GGUF conversion)")
    p.add_argument("--skip_merge",    action="store_true",
                   help="Skip merge step if merged model already exists")
    p.add_argument("--skip_convert",  action="store_true",
                   help="Skip GGUF conversion step")
    return p.parse_args()


def step1_merge(args, model_id: str, output_path: Path):
    """Merge LoRA adapter weights into the base model."""
    merged_path = output_path / "merged"

    if args.skip_merge and merged_path.exists():
        print(f"  [skip] Merged model already exists at {merged_path}")
        return merged_path

    print(f"\n[1/4] Merging LoRA adapter into base model…")
    print(f"      Base: {model_id}")
    print(f"      Adapter: {args.adapter_path}")

    print("      Loading base model (fp16, CPU-safe)…")
    base_model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.float16,
        device_map="cpu",        # merge on CPU to avoid VRAM OOM
        trust_remote_code=True,
    )

    print("      Loading LoRA adapter…")
    peft_model = PeftModel.from_pretrained(base_model, args.adapter_path)

    print("      Merging weights (this takes 1–5 minutes)…")
    merged_model = peft_model.merge_and_unload()

    print(f"      Saving merged model → {merged_path}")
    merged_model.save_pretrained(str(merged_path), safe_serialization=True)

    tokenizer = AutoTokenizer.from_pretrained(args.adapter_path, trust_remote_code=True)
    tokenizer.save_pretrained(str(merged_path))

    print(f"  [done] Merged model saved.")
    return merged_path


def step2_convert_gguf(args, merged_path: Path, output_path: Path):
    """Convert merged HuggingFace model to GGUF using llama.cpp."""
    gguf_path = output_path / f"{args.ollama_name}-{args.quantize}.gguf"

    if args.skip_convert and gguf_path.exists():
        print(f"\n  [skip] GGUF already exists at {gguf_path}")
        return gguf_path

    llama_cpp = Path(args.llama_cpp_dir)
    convert_script = llama_cpp / "convert_hf_to_gguf.py"

    if not llama_cpp.exists():
        print(f"\n[2/4] Cloning llama.cpp for GGUF conversion…")
        subprocess.run([
            "git", "clone", "--depth=1",
            "https://github.com/ggerganov/llama.cpp",
            str(llama_cpp)
        ], check=True)
        subprocess.run([sys.executable, "-m", "pip", "install",
                        "-r", str(llama_cpp / "requirements.txt")],
                       check=True)

    print(f"\n[2/4] Converting to GGUF ({args.quantize})…")

    # Step 2a: Convert to fp16 GGUF first
    fp16_gguf = output_path / f"{args.ollama_name}-f16.gguf"
    subprocess.run([
        sys.executable, str(convert_script),
        str(merged_path),
        "--outfile", str(fp16_gguf),
        "--outtype", "f16",
    ], check=True)

    # Step 2b: Quantize to target precision
    if args.quantize != "f16":
        quantize_bin = llama_cpp / "llama-quantize"
        if not quantize_bin.exists():
            quantize_bin = llama_cpp / "quantize"  # older llama.cpp name

        if not quantize_bin.exists():
            print("  [warn] llama-quantize binary not found — build llama.cpp first:")
            print("         cd llama.cpp && cmake -B build && cmake --build build -j")
            print(f"  [info] Using f16 GGUF: {fp16_gguf}")
            return fp16_gguf

        subprocess.run([
            str(quantize_bin),
            str(fp16_gguf),
            str(gguf_path),
            args.quantize.upper(),
        ], check=True)

        fp16_gguf.unlink(missing_ok=True)  # clean up large f16 file

    print(f"  [done] GGUF saved → {gguf_path}  ({gguf_path.stat().st_size / 1e9:.1f} GB)")
    return gguf_path


def step3_write_modelfile(args, gguf_path: Path, output_path: Path):
    """Write an Ollama Modelfile."""
    print(f"\n[3/4] Writing Ollama Modelfile…")

    modelfile_content = f"""FROM {gguf_path.resolve()}

SYSTEM \"\"\"{SYSTEM_PROMPT}\"\"\"

# Generation parameters — tuned for structured JSON output
PARAMETER temperature 0.05
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER num_predict 2000
PARAMETER num_ctx 4096

# Stop tokens (model-specific — adjust if using non-Qwen base)
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"
"""
    modelfile_path = output_path / "Modelfile"
    modelfile_path.write_text(modelfile_content, encoding="utf-8")
    print(f"  [done] Modelfile → {modelfile_path}")
    return modelfile_path


def step4_register_ollama(args, modelfile_path: Path):
    """Register the model with Ollama."""
    print(f"\n[4/4] Registering with Ollama as '{args.ollama_name}'…")
    try:
        subprocess.run([
            "ollama", "create", args.ollama_name,
            "-f", str(modelfile_path)
        ], check=True)
        print(f"\n  Model registered! Test it with:")
        print(f"    ollama run {args.ollama_name}")
        print(f"    >>> Create a flow to top up a customer phone number using the portal")
    except FileNotFoundError:
        print("  [warn] 'ollama' not found in PATH. Install Ollama first:")
        print("         https://ollama.ai/download")
        print(f"  Then run: ollama create {args.ollama_name} -f {modelfile_path}")
    except subprocess.CalledProcessError as e:
        print(f"  [error] Ollama registration failed: {e}")


def main():
    args = parse_args()
    model_id    = MODELS[args.model]
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"\nExporting fine-tuned model:")
    print(f"  Base:     {model_id}")
    print(f"  Adapter:  {args.adapter_path}")
    print(f"  Quant:    {args.quantize}")
    print(f"  Ollama:   {args.ollama_name}")

    merged_path   = step1_merge(args, model_id, output_path)
    gguf_path     = step2_convert_gguf(args, merged_path, output_path)
    modelfile_path = step3_write_modelfile(args, gguf_path, output_path)
    step4_register_ollama(args, modelfile_path)

    print(f"\n{'='*60}")
    print(" Export complete. Summary:")
    print(f"  Merged model: {output_path / 'merged'}")
    print(f"  GGUF:         {gguf_path}")
    print(f"  Modelfile:    {modelfile_path}")
    print(f"  Ollama name:  {args.ollama_name}")
    print(f"\n  To use in your QA agent, set in backend/.env:")
    print(f"    LLM_PROVIDER=ollama")
    print(f"    LLM_MODEL={args.ollama_name}")
    print(f"    USE_FLOW_AGENT=true")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
