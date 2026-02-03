# Repo Rating

Analyze code repositories to extract developer skills for resume building.

## Setup

```bash
# Install dependencies
pip install -e .

# Copy and fill in secrets
cp config_secret.example.toml config_secret.toml
# Edit config_secret.toml with your API keys
```

## Usage

```bash
# Analyze a GitHub repo
repo-rating analyze https://github.com/user/repo

# Analyze a local folder
repo-rating analyze /path/to/repo

# Analyze all public repos of a user
repo-rating analyze-user username
```

## Configuration
For github api key: https://github.com/settings/tokens

- `config.toml` - General settings (filtering patterns, model defaults)
- `config_secret.toml` - API keys (gitignored)
