"""
Auto-sort: find model files that sit in the wrong folder and move them.

A file's real kind (LoRA, checkpoint, VAE, ...) and base model come from its
hash-verified CivitAI sidecar and from the file itself (tensor layout and training
metadata in the safetensors/GGUF header). Which folder holds which base model is
learned from where most files already are.
"""
