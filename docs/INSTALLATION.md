# Installation Guide

Run the provided script to install all dependencies and download NLTK data:

```bash
./install.sh
```

The script installs packages listed in `requirements.txt` and executes
`nltk.download('all')` to fetch the complete NLTK dataset.

If you prefer to run the commands manually:

```bash
python -m pip install -r requirements.txt
python -m nltk.downloader all
```

Refer to the [README](../README.md) for configuration and usage details.
