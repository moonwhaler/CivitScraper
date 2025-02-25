# File Organization

Automatically organize your model files based on metadata from CivitAI. Files can be copied, moved, or symlinked into a structured directory layout.

## Configuration

Organization is configured in your YAML configuration file:

```yaml
organization:
  # Enable organization feature
  enabled: true

  # Use predefined template
  template: "by_type"

  # Or use custom template
  custom_template: "{base_model}/{type}/{creator}"

  # Output directory (can use {model_dir} for relative paths)
  output_dir: "organized_models"  # or "{model_dir}/organized"

  # Dry run mode (simulate operations without making changes)
  dry_run: false

  # Operation mode: "copy" (default), "move", or "symlink"
  operation_mode: "copy"
```

Enable organization in jobs:

```yaml
jobs:
  organize-all:
    description: "Organize all models"
    actions:
      - type: scan-paths
        paths: ["lora", "checkpoints"]
        recursive: true
        organize: true  # Enable organization after scanning
```

### Windows Symlink Requirements

When using symlinks (`operation_mode: "symlink"`) on Windows systems, one of the following conditions must be met:

1. Run the application with Administrator privileges
   - Right-click the application/terminal and select "Run as Administrator"

2. Enable Developer Mode (Windows 10 version 1703 or later)
   - Open Windows Settings
   - Navigate to Update & Security > For developers
   - Enable "Developer Mode"

If neither condition is met, symlink operations will fail with a permission error. In such cases, consider using copy (`operation_mode: "copy"`) or move (`operation_mode: "move"`) operations instead.

## Built-in Templates

### by_type
```
organized_models/
  ├── LORA/
  ├── Checkpoint/
  └── TextualInversion/
```

### by_creator
```
organized_models/
  ├── Creator1/
  └── Creator2/
```

### by_type_and_creator
```
organized_models/
  ├── LORA/
  │   ├── Creator1/
  │   └── Creator2/
  └── Checkpoint/
      ├── Creator1/
      └── Creator2/
```

### by_rating
```
organized_models/
  ├── rating_5/
  ├── rating_4/
  └── Unrated/
```

### by_base_model
```
organized_models/
  ├── SD1.5/
  └── SDXL/
```

### by_nsfw
```
organized_models/
  ├── sfw/
  └── nsfw/
```

### by_date
```
organized_models/
  ├── 2024/
  │   ├── 01/
  │   └── 02/
  └── 2023/
      ├── 11/
      └── 12/
```

## Custom Templates

Create custom organization structures using template variables:

```yaml
organization:
  custom_template: "{base_model}/{type}/{creator}/{model_name}"
```

Available variables:
- `{type}`: Model type (LORA, Checkpoint, etc.)
- `{creator}`: Creator username
- `{base_model}`: Base model name
- `{rating}`: Model rating (rounded)
- `{tags}`: First tag
- `{nsfw}`: NSFW status (sfw/nsfw)
- `{year}`: Creation year
- `{month}`: Creation month (2-digit)
- `{model_name}`: Model name from API
- `{model_type}`: Model type from API metadata

## Output Directory

The `output_dir` setting supports using the `{model_dir}` variable to organize files relative to their source directories:

```yaml
organization:
  # Global organization directory
  output_dir: "organized_models"

  # Or organize within model directories
  output_dir: "{model_dir}/organized"
```

## Operation Modes

Three operation modes are available via the `operation_mode` setting:

- **Copy** (default): Create copies of files
  ```yaml
  organization:
    operation_mode: "copy"
  ```

- **Move**: Move files to new locations
  ```yaml
  organization:
    operation_mode: "move"
  ```

- **Symlink**: Create symbolic links
  ```yaml
  organization:
    operation_mode: "symlink"
  ```

> **Note:** For backward compatibility, the legacy configuration using `move_files` and `create_symlinks` flags is still supported, but the `operation_mode` setting is recommended for new configurations.
