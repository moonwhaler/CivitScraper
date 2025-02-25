# Best Practices

Guidelines and practical use cases for using CivitScraper effectively. These recommendations will help you get the most out of the application while maintaining an organized and efficient workflow.

## Table of Contents
- [Model Organization](#model-organization)
  - [Directory Structure](#1-directory-structure)
  - [Metadata Storage Options](#2-metadata-storage-options)
- [Performance Optimization](#performance-optimization)
- [Maintenance Tips](#maintenance-tips)
- [Development Setup](#development-setup)
- [Production Setup](#production-setup)
- [Common Workflows](#common-workflows)

---

## Model Organization

### 1. Directory Structure
**Key Principles:**
- Keep similar model types together
- Use consistent naming conventions
- Consider subdirectories for different base models

### 2. Metadata Storage Options

#### Default: Next to Models
*Best for direct model management and simplicity*
```
models/
  ├── lora/
  │   ├── my_lora.safetensors
  │   └── my_lora.json           # Metadata here
  └── checkpoints/
      ├── my_model.safetensors
      └── my_model.json          # Metadata here
```

#### Separate Directory
*Good for centralized management and backup*
```
metadata/
  ├── lora/
  │   └── my_lora.json
  └── checkpoints/
      └── my_model.json
```

#### Mixed Approach
*Flexible organization based on model types and needs*
```yaml
# Store metadata in different locations using path variables
output:
  metadata:
    path: "{model_type}/{base_model}"  # Group by type and base model
    filename: "{model_name}.json"

input_paths:
  lora:
    path: "./models/Lora"
    type: LORA
    patterns: ["*.safetensors"]

  checkpoints:
    path: "./models/checkpoints"
    type: Checkpoint
    patterns: ["*.safetensors", "*.ckpt"]
```

**Path Variable Benefits:**
- `{model_dir}`: Store next to model files
- `{model_type}`: Group by model type
- `{base_model}`: Group by base model
- `{version}`: Include version information

## Performance Optimization

### 1. Batch Operations
**Recommended Settings:**
- Enable parallel processing
- Use response caching
- Configure rate limits based on API tier
- Group operations into jobs

### 2. Cache Management
**Best Practices:**
- Regular cache cleanup
- Adjust TTL based on update frequency
- Monitor cache size
- Implement cache rotation

---

## Maintenance Tips

### 1. Regular Updates
**Update Strategy:**
- Configure a job with `skip_existing: false` to update all metadata
- Run the job using your configured job settings
- Schedule updates during off-peak hours

### 2. Backup Strategy
**Data Protection:**
- Back up centralized metadata
- Version control for configs
- Archive important model data
- Maintain backup rotation

### 3. Monitoring
**System Health:**
- Check batch operation logs
- Monitor API rate limits
- Track failed operations
- Set up alerts for issues

---

## Development Setup

**Development Environment Configuration:**

```yaml
# dev-config.yaml
input_paths:
  development:
    path: "./models/development"
    type: LORA
    recursive: true
    patterns: ["*.safetensors"]

output:
  metadata:
    path: "{model_dir}"
    filename: "{model_name}.json"  # JSON metadata file
    html:
      enabled: true  # Enable HTML generation
```

## Production Setup

**Production Environment Configuration:**

```yaml
# prod-config.yaml
input_paths:
  checkpoints:
    path: "/models/stable-diffusion"
    type: Checkpoint
    patterns: ["*.safetensors", "*.ckpt"]
  lora:
    path: "/models/lora"
    type: LORA
    patterns: ["*.safetensors", "*.pt"]
  embeddings:
    path: "/models/embeddings"
    type: TextualInversion
    patterns: ["*.pt", "*.safetensors"]

output:
  metadata:
    path: "/metadata/{model_type}/{base_model}"
    filename: "{model_name}.json"  # JSON metadata file
    html:
      enabled: true  # Enable HTML generation
```

## Common Workflows

### 1. Initial Setup
**First-Time Configuration:**
   ```yaml
   jobs:
     initial-setup:
       description: "Initial setup job"
       actions:
         - type: scan-paths
           paths: ["all"]  # Scan all configured paths
           recursive: true
           skip_existing: true
           verify_hashes: true
           organize: true  # Run organization after scanning
   ```

### 2. Maintenance
**Regular Maintenance Tasks:**
   ```yaml
   jobs:
     update-all:
       description: "Update all metadata"
       actions:
         - type: scan-paths
           paths: ["all"]
           recursive: true
           skip_existing: false  # Force update
           verify_hashes: true
   ```

### 3. Batch Processing
**Efficient Batch Operations:**
   ```yaml
   jobs:
     process-specific:
       description: "Process specific model types"
       actions:
         - type: scan-paths
           paths: ["lora", "checkpoints"]
           recursive: true
           skip_existing: true
           verify_hashes: true
   ```

### 4. Organization
**File Organization Strategy:**
   ```yaml
   jobs:
     organize-models:
       description: "Organize models by type and creator"
       actions:
         - type: scan-paths
           paths: ["all"]
           recursive: true
           skip_existing: true
           verify_hashes: true
           organize: true
   ```
