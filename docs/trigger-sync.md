# Krita AI Diffusion Trigger Word Synchronization

Synchronize trigger words between model JSON files and the special Krita AI Diffusion "loras.json" file for centralized LoRA trigger word management.

## Table of Contents
- [Configuration](#configuration)
  - [Template Requirements](#template-requirements)
  - [Example Configuration](#example-configuration)
- [Output and Reporting](#output-and-reporting)
- [How It Works](#how-it-works)
- [Example Files](#example-files)
- [Notes](#notes)

---

## Configuration

Trigger word synchronization is enabled through input path configuration and job templates:

### Template Requirements

The sync-lora-triggers template type requires specific fields to function correctly:
- `type`: (string, required) - Must be 'sync-lora-triggers'
- `loras_file`: (string or path, required) - Path to the loras.json file
- `paths`: (array of strings, required) - List of input_paths IDs to scan for models
- `recursive`: (boolean, required) - Whether to search subdirectories
- `description`: (string, optional) - Human-readable description of the template

### Example Configuration

Below is a complete example showing how to configure trigger word synchronization:

```yaml
# Configure input paths
input_paths:
  lora:
    path: "./models/Lora"
    type: LORA
    patterns: ["*.safetensors"]  # Only .safetensors files are supported

# Define the trigger sync template
job_templates:
  sync_triggers:
    type: sync-lora-triggers
    description: "Synchronize LoRA trigger words"
    loras_file: "loras.json"  # Path to loras.json file
    recursive: true  # Whether to search subdirectories
    paths: []  # Empty array as default, should be overridden when creating a job

# Create a sync job using the template
jobs:
  sync-triggers:
    template: sync_triggers  # Use the trigger sync template
    paths: ["lora"]  # Reference input_paths by ID
    loras_file: "./custom/path/loras.json"  # Optional: Override loras.json location
```

**Operation Steps:**
1. Look for a `loras.json` file (configurable via loras_file setting)
2. Search for model JSON files in the configured paths
3. Update `loras.json` with trigger words from model metadata

**Template Benefits:**
- Clear separation of trigger sync functionality
- Configurable loras.json location
- Control over recursive directory searching
- Ability to override the loras.json path per job

---


## Output and Reporting

The sync operation provides detailed feedback to help track the synchronization process:
- Success messages for each successfully processed file
- Error messages for any failures (missing files, invalid formats, etc.)
- Summary of total files processed and any skipped files

Example output:
```
Found 5 model files
Success: Successfully processed models/Lora/arcaneStyleLora_v1.safetensors: Found activation text
Warning: Skipping models/Lora/other_model.safetensors - no JSON file found
Success: Updated 1 entries in loras file
```

## How It Works

The synchronization process follows these steps:
1. Reads the loras.json file
2. Looks for corresponding JSON files in specified path
3. Extracts "activation text" from model JSON files
4. Updates (Krita AI Diffusion) loras.json with trigger words

---

## Example Files

Below are examples of the files involved in the synchronization process:

### Model JSON (arcaneStyleLora_v1.json)
```json
{
  "sha256": "F15429D21C6B54B32577BE32DFEEBA7F7FF13CB4585432E59FE20D88D83C1C51",
  "modelId": 7094,
  "activation text": "arcane style",
  "description": null,
  "baseModel": "SD 1.5",
  "model": {
    "name": "Arcane Style LoRA",
    "type": "LORA",
    "nsfw": false
  }
}
```

### Before Sync (loras.json)
```json
{
  "id": "1.5/Style/arcaneStyleLora_v1.safetensors",
  "name": "1.5/Style/arcaneStyleLora_v1",
  "source": 2,
  "format": "lora"
}
```

### After Sync
```json
{
  "id": "1.5/Style/arcaneStyleLora_v1.safetensors",
  "name": "1.5/Style/arcaneStyleLora_v1",
  "source": 2,
  "format": "lora",
  "metadata": {
    "lora_triggers": "arcane style"
  }
}
```

## Notes

**Important Considerations:**
- The `loras.json` file must exist at the specified path
- Only `.safetensors` files with corresponding `.json` metadata files are processed
- Trigger words are read from the "activation text" field in model metadata
- The sync is one-way: from model metadata to `loras.json`
- Trigger words can be stored as either strings or arrays in the loras.json metadata
