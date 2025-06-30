from flask import Flask, render_template, request
import requests
import re # For regex matching of file patterns

app = Flask(__name__)

# Define heuristics for identifying unnecessary files
# List of (regex_pattern, reason_string, is_dir_pattern)
# is_dir_pattern helps to match if the path IS a directory or STARTS WITH a directory name
UNNECESSARY_FILE_PATTERNS = [
    (r"\.log$", "Log file", False),
    (r"\.tmp$", "Temporary file", False),
    (r"\.temp$", "Temporary file", False),
    (r"\.bak$", "Backup file", False),
    (r"\.swp$", "Swap file", False),
    (r"\.swo$", "Swap file", False),
    (r"~$", "Backup file (tilde)", False), # Files ending with ~
    (r"\.DS_Store$", "macOS specific metadata file", False),
    (r"Thumbs\.db$", "Windows specific metadata file", False),
    (r"\.cache$", "Cache file", False),
    (r"\.coverage$", "Code coverage data", False),

    # Compiled files
    (r"\.o$", "Compiled object file", False),
    (r"\.obj$", "Compiled object file", False),
    (r"\.class$", "Java compiled class file", False),
    (r"\.pyc$", "Python compiled bytecode file", False),
    (r"\.dll$", "Dynamic Link Library (often build output)", False),
    (r"\.so$", "Shared object file (often build output)", False),
    (r"\.exe$", "Executable file (often build output)", False),
    (r"\.out$", "Output file (often build/compiler output)", False),
    (r"\.app$", "macOS Application bundle (often build output)", True),


    # Build directories / Package manager directories
    (r"^build/", "Build output directory", True),
    (r"^dist/", "Distribution directory", True),
    (r"^target/", "Build target directory (e.g., Java/Rust)", True),
    (r"^bin/", "Binary output directory (heuristic)", True), # Can be source too, so user should check
    (r"^obj/", "Object file directory (heuristic)", True), # Can be source too
    (r"node_modules/", "Node.js dependencies directory", True),
    (r"__pycache__/", "Python bytecode cache directory", True),
    (r"\.idea/", "JetBrains IDE project files", True),
    (r"\.vscode/", "VS Code editor project files", True),
    (r"\.project$", "Eclipse project file", False),
    (r"\.classpath$", "Eclipse classpath file", False),
    (r"\.settings/", "Eclipse settings directory", True),
    (r"venv/", "Python virtual environment directory", True),
    (r"env/", "Python virtual environment directory", True),
    (r"\.env$", "Environment configuration file (often local)", False), # .env files can sometimes contain secrets
    (r"\.venv/", "Python virtual environment directory", True),
    (r"^(.*\.egg-info)/", "Python egg info directory", True),

    # Archives (less common to ignore all, but sometimes specific ones)
    (r"\.zip$", "ZIP archive (check if build artifact)", False),
    (r"\.tar\.gz$", "TGZ archive (check if build artifact)", False),
    (r"\.tgz$", "TGZ archive (check if build artifact)", False),
    (r"\.jar$", "Java archive (check if build artifact or dependency)", False),
    (r"\.war$", "Java web archive (check if build artifact)", False),

    # IDE specific / OS specific
    (r"desktop\.ini$", "Windows desktop configuration file", False),
    (r"\.Trash/", "Trash directory", True),
    (r"\.Spotlight-V100/", "macOS Spotlight index", True),
    (r"\.fseventsd/", "macOS file system events log", True),
]

def suggest_files_to_ignore(filename_with_path, file_infos):
    """
    Analyzes a file path and suggests if it should be ignored.
    Returns (is_suggested_to_ignore, suggestion_reason)
    file_infos can be used if we need to know if a path is a directory (not directly available from commit files list)
    For now, we rely on patterns that include directory markers like trailing slashes or specific names.
    """
    for pattern, reason, is_dir_pattern in UNNECESSARY_FILE_PATTERNS:
        # If it's a directory pattern, we check if the filename_with_path starts with it
        # or exactly matches if the pattern doesn't have a trailing slash implicit in its nature (like node_modules/)
        if is_dir_pattern:
            # Ensure pattern for dir check ends with / if it's a prefix, or is an exact match for dir name
            # e.g. pattern "node_modules/" should match "node_modules/file.js"
            # pattern "build" should match "build/" (if we assume build is always a dir)
            # This logic can be tricky without knowing if `filename_with_path` is a dir itself.
            # For now, simple prefix matching for dir patterns.
            if pattern.endswith('/'): # e.g. "node_modules/"
                if filename_with_path.startswith(pattern):
                    return True, reason
            else: # e.g. pattern r"^build/" or r"\.idea/"
                 if re.search(pattern, filename_with_path): # Using re.search for patterns like r"^build/"
                    return True, reason
        else: # It's a file pattern
            if re.search(pattern, filename_with_path):
                return True, reason
    return False, ""


@app.route('/', methods=['GET', 'POST'])
def index():
    error = None
    repo_url = request.form.get('repo_url') if request.method == 'POST' else request.args.get('repo_url', '')
    branches = []

    if request.method == 'POST' and 'fetch_branches' in request.form:
        if not repo_url:
            error = "Repository URL is required."
        else:
            try:
                parts = repo_url.strip('/').split('/')
                if len(parts) < 2 or parts[-2] == '' or parts[-1] == '':
                    raise ValueError("Invalid GitHub repository URL format.")

                user, repo = parts[-2], parts[-1]
                api_url = f"https://api.github.com/repos/{user}/{repo}/branches"
                # Add headers for GitHub API v3, especially if dealing with many branches or private repos (later)
                # headers = {'Accept': 'application/vnd.github.v3+json'}
                # response = requests.get(api_url, headers=headers)
                response = requests.get(api_url)
                response.raise_for_status()
                branches_data = response.json()

                if not branches_data:
                    error = "No branches found for this repository or repository is empty/invalid."

                for branch_data in branches_data:
                    branches.append({
                        'name': branch_data['name'],
                        'sha': branch_data['commit']['sha'] # SHA of the commit the branch points to
                    })

            except ValueError as ve:
                error = str(ve)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    error = "Repository not found. Please check the URL."
                else:
                    error = f"Error fetching branches: {e}"
            except requests.exceptions.RequestException as e:
                error = f"Error fetching branches: {e}"
            except Exception as e:
                error = f"An unexpected error occurred: {e}"

    return render_template('index.html', error=error, repo_url=repo_url, branches=branches)


@app.route('/commits_for_branch', methods=['GET', 'POST'])
def commits_for_branch():
    if request.method == 'POST':
        repo_url = request.form.get('repo_url')
        branch_name = request.form.get('branch_name')
    else: # GET request
        repo_url = request.args.get('repo_url')
        branch_name = request.args.get('branch_name')

    commits = []
    error = None

    if not repo_url or not branch_name:
        error = "Repository URL and branch name are required."
        # For GET, if params are missing, it might be better to redirect to index or show a clear error.
        return render_template('index.html', error=error, repo_url=repo_url, branches=[]) # Ensure branches is passed if index expects it

    try:
        parts = repo_url.strip('/').split('/')
        user, repo = parts[-2], parts[-1]
        # GitHub API to get commits for a specific branch
        api_url = f"https://api.github.com/repos/{user}/{repo}/commits?sha={branch_name}"
        response = requests.get(api_url)
        response.raise_for_status()
        commits_data = response.json()

        for commit_data in commits_data[:30]: # Limit to 30 commits
            commits.append({
                'sha': commit_data['sha'],
                'message': commit_data['commit']['message'].splitlines()[0],
                'author': commit_data['commit']['author']['name'],
                'date': commit_data['commit']['author']['date']
            })
    except requests.exceptions.RequestException as e:
        error = f"Error fetching commits for branch {branch_name}: {e}"
    except Exception as e:
        error = f"An unexpected error occurred: {e}"

    # We need a new template or modify index.html to show commits after branch selection
    # For now, let's reuse parts of index.html logic by passing commits list.
    # This means index.html needs to be able to handle displaying commits OR branches.
    return render_template('index.html', repo_url=repo_url, selected_branch_name=branch_name, commits=commits, error=error)


@app.route('/select_commit', methods=['GET', 'POST'])
def select_commit():
    branch_name = None
    if request.method == 'POST':
        repo_url = request.form.get('repo_url')
        commit_sha = request.form.get('commit_sha')
        branch_name = request.form.get('branch_name') # Get branch name from form
    else: # GET request
        repo_url = request.args.get('repo_url')
        commit_sha = request.args.get('commit_sha')
        branch_name = request.args.get('branch_name') # Get branch name from args

    files = []
    error = None

    if not repo_url or not commit_sha:
        error = "Repository URL or Commit SHA missing."
        return render_template('index.html', error=error, repo_url=repo_url, selected_branch_name=branch_name)

    # It's good practice to also check for branch_name if it's essential for the API calls,
    # though commit SHA is usually unique across branches for fetching commit details.
    # However, for context (like the "back" button), it's good to keep it.

    try:
        parts = repo_url.strip('/').split('/')
        if len(parts) < 2:
            raise ValueError("Invalid GitHub repository URL format.")
        user, repo = parts[-2], parts[-1]

        # GitHub API endpoint to get a specific commit, which includes file list
        api_url = f"https://api.github.com/repos/{user}/{repo}/commits/{commit_sha}"
        response = requests.get(api_url)
        response.raise_for_status()
        commit_data = response.json()

        if 'files' in commit_data:
            for file_info in commit_data['files']:
                is_suggested, reason = suggest_files_to_ignore(file_info['filename'], commit_data['files'])
                files.append({
                    'filename': file_info['filename'],
                    'status': file_info['status'],
                    'is_suggested_to_ignore': is_suggested,
                    'suggestion_reason': reason
                })
        else: # Fallback for commits where 'files' might not be directly available (e.g. very old commits or merge commits without file changes listed directly)
            tree_sha = commit_data['commit']['tree']['sha']
            tree_api_url = f"https://api.github.com/repos/{user}/{repo}/git/trees/{tree_sha}?recursive=1"
            tree_response = requests.get(tree_api_url)
            tree_response.raise_for_status()
            tree_data = tree_response.json()
            if 'tree' in tree_data:
                # Note: tree_data['tree'] might contain directories as well.
                # suggest_files_to_ignore needs to handle this.
                # The 'status' isn't available here, defaults to 'unknown'.
                for item in tree_data['tree']:
                    if item['type'] == 'blob': # Only process files (blobs)
                        is_suggested, reason = suggest_files_to_ignore(item['path'], tree_data['tree'])
                        files.append({
                            'filename': item['path'],
                            'status': 'unknown',
                            'is_suggested_to_ignore': is_suggested,
                            'suggestion_reason': reason
                        })
    except ValueError as ve:
        error = str(ve)
    except requests.exceptions.RequestException as e:
        error = f"Error fetching commit details: {e}"
    except Exception as e:
        error = f"An unexpected error occurred while fetching files: {e}"

    # For now, we'll pass repo_url and commit_sha to a new template or extend index.html
    # This will be refined in subsequent steps to show files and allow selection.
    return render_template('commit_files.html',
                           repo_url=repo_url,
                           commit_sha=commit_sha,
                           files=files,
                           error=error,
                           branch_name=branch_name) # Pass branch_name to template

@app.route('/process_files', methods=['POST'])
def process_files():
    repo_url = request.form.get('repo_url')
    commit_sha = request.form.get('commit_sha')
    branch_name = request.form.get('branch_name') # Get branch name
    selected_files = request.form.getlist('selected_files')

    if not repo_url or not commit_sha:
        # Handle error, maybe redirect to index or show an error message
        return "Error: Missing repository URL or commit SHA.", 400

    # Fetch file list again for re-rendering if no files selected.
    # This is a simplified re-fetch. A more robust app might pass files list through session or hidden form fields.
    commit_files_for_template = []
    if not selected_files:
        try:
            parts = repo_url.strip('/').split('/')
            user, repo = parts[-2], parts[-1]
            api_url = f"https://api.github.com/repos/{user}/{repo}/commits/{commit_sha}"
            response = requests.get(api_url)
            response.raise_for_status()
            commit_data = response.json()
            if 'files' in commit_data:
                for file_info in commit_data['files']:
                    commit_files_for_template.append({'filename': file_info['filename'], 'status': file_info['status']})
            else: # Fallback for older commits or different structures
                tree_sha = commit_data['commit']['tree']['sha']
                tree_api_url = f"https://api.github.com/repos/{user}/{repo}/git/trees/{tree_sha}?recursive=1"
                tree_response = requests.get(tree_api_url)
                tree_response.raise_for_status()
                tree_data = tree_response.json()
                if 'tree' in tree_data:
                    for item in tree_data['tree']:
                        if item['type'] == 'blob':
                             commit_files_for_template.append({'filename': item['path'], 'status': 'unknown'})
        except Exception:
            # If re-fetching files fails, pass an empty list and let the template handle it.
            pass

        error_message = "No files were selected. Please select at least one file."
        return render_template('commit_files.html',
                               repo_url=repo_url,
                               commit_sha=commit_sha,
                               files=commit_files_for_template, # Pass the fetched files
                               error=error_message,
                               branch_name=branch_name) # Pass branch_name back

    # Generate .gitignore entries
    gitignore_entries = []
    if selected_files:
        for file_path in selected_files:
            gitignore_entries.append(file_path)
            if '.' in file_path:
                ext = file_path.split('.')[-1]
                if ext and not f"*.{ext}" in gitignore_entries:
                    gitignore_entries.append(f"*.{ext}")

    # Generate cleanup command
    cleanup_command = ""
    if selected_files:
        filter_repo_paths_options = " ".join([f"--path \"{file}\"" for file in selected_files])
        repo_name_for_clone = repo_url.split('/')[-1]
        if repo_name_for_clone.endswith('.git'):
            repo_name_for_clone = repo_name_for_clone[:-4]

        cleanup_command = (
            f"# 1. Clone a fresh mirror of your repository:\n"
            f"git clone --mirror {repo_url} {repo_name_for_clone}.git-mirror\n\n"
            f"# 2. Navigate into the mirrored repository:\n"
            f"cd {repo_name_for_clone}.git-mirror\n\n"
            f"# 3. Ensure you have git-filter-repo installed (e.g., pip install git-filter-repo).\n\n"
            f"# 4. Run git filter-repo to remove the selected files from all of history:\n"
            f"#    (This command removes the files entirely. Use with extreme caution!)\n"
            f"git filter-repo --invert-paths {filter_repo_paths_options}\n\n"
            f"# 5. Inspect your repository to ensure the changes are correct.\n"
            f"#    For example, check commit history and file contents.\n\n"
            f"# 6. If satisfied, force push the changes to your original remote repository:\n"
            f"#    WARNING: This overwrites history on the remote. Ensure all collaborators are aware.\n"
            f"#    First, find your remote name (usually 'origin'). If you cloned from {repo_url},\n"
            f"#    the remote 'origin' should already point there.\n"
            f"git push origin --force --all\n"
            f"git push origin --force --tags\n\n"
            f"# IMPORTANT NOTES:\n"
            f"# - ALWAYS BACKUP YOUR ORIGINAL REPOSITORY BEFORE PERFORMING THESE ACTIONS.\n"
            f"# - The commit SHA ({commit_sha[:7]}) you initially selected was on branch '{branch_name}'.\n"
            f"#   The command above cleans history across ALL branches and tags.\n"
            f"# - If you only want to remove files from a specific commit or range, \n"
            f"#   `git filter-repo` has more advanced options, or consider an interactive rebase (`git rebase -i`)."
        )

    return render_template('results.html',
                           repo_url=repo_url,
                           commit_sha=commit_sha,
                           selected_files=selected_files,
                           gitignore_entries=gitignore_entries,
                           cleanup_command=cleanup_command,
                           branch_name=branch_name) # Pass branch_name to results


if __name__ == '__main__':
    app.run(debug=True)
