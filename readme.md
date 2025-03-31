# CivitScraper: Tidy Up Your AI Models!

![Example of a generated HTML file](civiscraper_html_example.png)

Tired of digging through messy folders to find your AI models? **CivitScraper** is here to help! It automatically organizes your downloaded models (like LoRAs, Checkpoints, etc.), fetches useful info and preview images from CivitAI, and creates easy-to-browse HTML pages for your collection.

**What CivitScraper Does For You:**

*   **Finds Your Models:** Scans the folders you specify.
*   **Gets Model Info:** Downloads details like creator, type, trigger words, and ratings from CivitAI.
*   **Downloads Previews:** Grabs preview images so you can see what the model does.
*   **Organizes Files (Optional):** Arranges your models, info files, and images into a clean folder structure.
*   **Creates Visual Previews:** Generates HTML pages for each model and a main gallery page to easily browse your collection.

---

## Quickest Start

Let's get you up and running quickly.

1.  **Get the Code and Install:**
    *   Open your terminal or command prompt.
    *   Clone the repository (downloads the code):
        ```bash
        git clone https://github.com/moonwhaler/civitscraper.git
        ```
    *   Navigate into the downloaded folder:
        ```bash
        cd civitscraper
        ```
    *   *(Recommended)* Create and activate a Python virtual environment to keep dependencies isolated:
        ```bash
        # Create environment (named 'venv')
        python -m venv venv
        # Activate it
        # Windows: venv\Scripts\activate
        # macOS/Linux: source venv/bin/activate
        ```
    *   Install CivitScraper and its requirements:
        ```bash
        pip install -e .
        ```

2.  **Create a Basic Configuration File:**
    *   Create a folder named `config` in your project directory (if it doesn't exist).
    *   Inside the `config` folder, create a file named `default.yaml`.
    *   Copy and paste the following minimal configuration into `config/default.yaml`:

    ```yaml
    # config/default.yaml
    input_paths:
      # --- Tell CivitScraper where ONE folder of your models is ---
      my_loras: # You can name this anything (e.g., my_checkpoints)
        path: "/path/to/your/lora/models" # <--- !!! CHANGE THIS to the ACTUAL path !!!
        type: LORA                        # Helps identify model type (e.g., LORA, Checkpoint)
        patterns: ["*.safetensors", "*.pt"] # File types to look for

    # --- Define a simple task (job) ---
    jobs:
      # This job scans the path defined above, gets info, and makes HTML pages
      fetch_and_preview:
        type: scan-paths
        paths: ["my_loras"] # Use the name you chose under input_paths
        output:
          metadata:
            html:
              enabled: true # Create HTML previews? Yes!
              generate_gallery: true # Create a main gallery page? Yes!
              gallery_path: "gallery.html" # Name for the main gallery file

    # --- Which job to run by default ---
    default_job: fetch_and_preview

    # --- Optional: Add your CivitAI API Key for better performance ---
    # api:
    #   key: "YOUR_API_KEY_HERE" # Get from your CivitAI Account Settings

    # --- Required API Endpoint ---
    api:
      base_url: "https://civitai.com/api/v1"
    ```
    *   **IMPORTANT:** Change `/path/to/your/lora/models` to the actual path where you store those models!

3.  **Run CivitScraper:**
    In your terminal (in the same directory where your `config` folder is), simply run:
    ```bash
    civitscraper
    ```

4.  **Check the Results:**
    *   Look inside your model folder (`/path/to/your/lora/models`). You should see new `.json` files next to your models, containing the fetched metadata.
    *   You should also see `.html` files for each model and potentially downloaded preview images.
    *   In the directory where you ran the command, you should find a `gallery.html` file. Open it in your web browser to see your model gallery!

That's it! You've successfully scanned your models and created visual previews.

---

## How CivitScraper Works (The Big Picture)

1.  **Scan:** CivitScraper looks in the folders you defined (`input_paths`) for model files matching the `patterns`.
2.  **Identify:** It calculates a unique "fingerprint" (hash) for each file.
3.  **Fetch:** It asks the CivitAI API for information about models matching that fingerprint.
4.  **Save Info:** It saves the details (metadata) into a `.json` file next to your model.
5.  **Download Images (Optional):** If configured, it downloads preview images listed in the metadata.
6.  **Generate HTML (Optional):** If configured, it creates an `.html` page for the model using the info and images. It can also create a central `gallery.html`.
7.  **Organize (Optional):** If configured, it can move, copy, or link (`symlink`) the model file and its associated info/image/HTML files into a structured directory based on the model's metadata (e.g., by type, creator).

---

## Installation

### Requirements

*   Python 3.8 or higher
*   An internet connection (to talk to the CivitAI API)

### Steps

While `pip install civitscraper` (shown in the Quick Start) is the easiest, if you want to modify the code or contribute, you'll want to clone the repository:

```bash
# 1. Clone the repository (if you haven't already)
git clone https://github.com/moonwhaler/civitscraper.git
cd civitscraper

# 2. Create a Python Virtual Environment (Recommended!)
# This keeps dependencies separate from your system Python.
python -m venv venv

# 3. Activate the virtual environment
# On Windows (cmd/powershell):
venv\Scripts\activate
# On macOS/Linux (bash/zsh):
source venv/bin/activate
# (Your terminal prompt should now show '(venv)' at the beginning)

# 4. Install CivitScraper in editable mode
pip install -e .

# 5. Verify installation
civitscraper --help

# 6. When finished, deactivate the environment
deactivate
```

---

## Basic Configuration (`config/default.yaml`)

CivitScraper uses a configuration file written in YAML format (usually `config/default.yaml`). YAML is human-readable and uses indentation (spaces, not tabs!) to define structure.

The Quick Start showed a minimal example. Here are the key sections you'll typically configure:

### `input_paths` (Required)

Tell CivitScraper where to find your models. You need at least one entry.

```yaml
input_paths:
  # Give each path a unique name (e.g., loras, checkpoints, embeddings)
  loras:
    path: "/path/to/your/lora/models"  # <--- CHANGE THIS
    type: LORA                         # Helps identify model type
    patterns: ["*.safetensors", "*.pt"] # Files to look for

  checkpoints:
    path: "/path/to/your/checkpoints" # <--- CHANGE THIS
    type: Checkpoint
    patterns: ["*.safetensors", "*.ckpt"]

  # Add more for other types as needed
  # embeddings:
  #   path: "/path/to/embeddings"
  #   type: TextualInversion
  #   patterns: ["*.pt", "*.safetensors"]
```

### `api.key` (Optional, Recommended)

Providing your CivitAI API key allows CivitScraper to make more requests to CivitAI before potentially getting rate-limited.

```yaml
api:
  key: "YOUR_API_KEY_HERE" # Get from your CivitAI Account Settings -> API Keys
```

### `jobs` (Required)

Jobs define *what* CivitScraper should do. You need at least one job. The `scan-paths` type is the most common.

```yaml
jobs:
  # Give your job a unique name
  fetch_and_preview:
    type: scan-paths             # This type scans folders for models
    paths: ["loras", "checkpoints"] # Which input_paths to scan for this job

    # --- Output Settings (within the job) ---
    output:
      metadata:
        # Settings for the .json info files
        path: "{model_dir}"            # Save .json in the same directory as the model
        filename: "{model_name}.json"  # How to name the .json file

        # Settings for the .html preview pages
        html:
          enabled: true                # Generate HTML pages?
          filename: "{model_name}.html" # How to name the .html file
          generate_gallery: true       # Generate a main gallery.html?
          gallery_path: "gallery.html" # Where to save the main gallery
          gallery_title: "My Model Gallery" # Browser title for the gallery

      images:
        # Settings for downloading preview images
        save: true                     # Download images?
        path: "{model_dir}"            # Save images in the same directory as the model
        max_count: 5                   # Max images per model

    # --- Organization Settings (Optional, within the job) ---
    # organization:
    #   enabled: false                 # Enable file organization? (Default: false)
    #   output_dir: "{model_dir}/organized" # Where to put organized files
    #   template: "by_type_and_creator" # How to structure folders (e.g., LORA/CreatorName/...)
    #   operation_mode: "symlink"      # How to organize: symlink (safe), copy, or move (caution!)
    #   dry_run: false                 # Set to true to test without changing files

# --- Default Job ---
default_job: fetch_and_preview # Which job runs when you just type 'civitscraper'
```

> **For many more configuration options** (like advanced API settings, caching, custom organization templates, logging, other job types), please see the detailed **[CONFIGURATION.md](CONFIGURATION.md)** file.

---

## Running the Scraper

Once configured, run CivitScraper from your terminal (make sure your virtual environment is active if you used one).

```bash
# Run the job specified by 'default_job' in your config
civitscraper

# Run a specific job defined in your config
civitscraper --job <job_name>
# Example: civitscraper -j fetch_and_preview

# Run all defined jobs sequentially
civitscraper --all-jobs

# Test organization without actually moving/copying files
# (Requires organization to be enabled in the job config)
civitscraper --job <job_name_with_org> --dry-run

# Force CivitScraper to ignore cached API data and get fresh info
civitscraper --force-refresh

# Show detailed logs for troubleshooting
civitscraper --debug

# Use a different configuration file
civitscraper --config /path/to/your/custom_config.yaml
```

---

## What You Get (Key Features Explained Simply)

### Browsing Your Models Visually (HTML Previews & Gallery)

*   **Problem:** Hard to remember what each `.safetensors` file does.
*   **Solution:** CivitScraper generates an `.html` page for each model, showing its preview images, description, trigger words, creator, etc. It also creates a main `gallery.html` linking to all individual pages, giving you a visual overview of your collection.
*   **How:** Enable `output.metadata.html.enabled: true` and `output.metadata.html.generate_gallery: true` in your job configuration.

### Organizing Your Files Automatically (Optional)

*   **Problem:** Model download folders become a mess.
*   **Solution:** CivitScraper can automatically rearrange your model files (and their `.json`/`.html`/images) into a clean folder structure based on info like model type, creator, or base model.
*   **How:** Enable `organization.enabled: true` in a job. Choose a `template` (like `by_type_and_creator`) and an `operation_mode`.
    *   `symlink` (Recommended): Creates shortcuts/links to your original files, keeping originals safe.
    *   `copy`: Duplicates files into the organized structure.
    *   `move` (Use with Caution!): Moves original files.
*   **Safety First:** Always test with `dry_run: true` in the config or `--dry-run` on the command line first to see what *would* happen without actually changing anything! Back up your models before using `move`.
*   **Details:** For available templates and custom structures, see [Organization Settings in CONFIGURATION.md](CONFIGURATION.md#organization).

### Understanding the Metadata (`.json` Files)

*   **Problem:** You need the model's trigger words or other details without opening the web UI.
*   **Solution:** CivitScraper saves all the fetched info from CivitAI into a `.json` file next to your model. This file contains details like name, creator, type, base model, tags, description, trigger words (`trainedWords`), ratings, and image URLs.
*   **How:** This happens automatically when CivitScraper fetches metadata. You can configure the filename and path in `output.metadata`.

---

## Advanced Topics

CivitScraper has more advanced capabilities configured in `config/default.yaml` and explained fully in **[CONFIGURATION.md](CONFIGURATION.md)**:

*   **Job System:** Define multiple, specific tasks (e.g., only fetch metadata, only organize, sync Krita triggers). See [Job System in CONFIGURATION.md](CONFIGURATION.md#job-system).
*   **Krita AI Diffusion Integration:** Automatically update Krita's trigger words for your LoRAs. See [Krita Integration in CONFIGURATION.md](CONFIGURATION.md#krita-ai-diffusion-integration).
*   **API Performance & Caching:** Fine-tune how CivitScraper interacts with the CivitAI API (rate limits, timeouts, caching) for smoother operation on large collections. See [API Settings in CONFIGURATION.md](CONFIGURATION.md#api).
*   **Custom Organization:** Define your own complex folder structures using placeholders. See [Custom Organization Templates in CONFIGURATION.md](CONFIGURATION.md#custom-organization-template).
*   **Detailed Logging:** Configure log levels and file output for advanced debugging. See [Logging Settings in CONFIGURATION.md](CONFIGURATION.md#logging).

---

## Troubleshooting

*   **"File Not Found" Errors:** Double-check the `path` under `input_paths` in `config/default.yaml`. Make sure it's the correct, full path to your model directory. Check folder permissions.
*   **API Key / Rate Limit Errors (401, 429):** Ensure your `api.key` (if used) is correct. If you see "429 Too Many Requests", CivitAI is limiting you. CivitScraper tries to handle this, but you might need to wait or adjust `api.batch.rate_limit` (see `CONFIGURATION.md`). Using a valid API key helps.
*   **Organization Not Working:**
    *   Is `organization.enabled: true` in the specific job you're running?
    *   Did you test with `--dry-run` first? Check the log output (use `--debug` for details).
    *   Is the `organization.output_dir` path valid and writable?
*   **Need More Detail?** Run with `--debug` for verbose logs: `civitscraper --debug`. Check the `logs` folder (configurable via `logging.file.directory`).

---

## Development

Interested in contributing?

1.  Follow the Installation steps using `git clone` and `pip install -e .`.
2.  Install development dependencies: `pip install -r requirements-dev.txt`
3.  **Testing:** Uses `pytest`. Run tests with `pytest`. Run coverage with `pytest --cov=civitscraper`.
4.  **Code Quality:** Uses `pre-commit` for formatting (black, isort) and linting (flake8, mypy).
    *   Install hooks: `pre-commit install`
    *   Run manually: `pre-commit run --all-files` (Hooks also run automatically on commit).

---

## License

CivitScraper is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

See the [LICENSE](LICENSE) file for the full text.

**In short:** You can freely use, modify, and share this software. If you distribute modified versions (or provide network access to a modified version), you **must** also share your modified source code under the same AGPL-3.0 license.
