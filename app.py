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
    # For directory patterns, use (^|/) to match if it's at the start of path or preceded by /
    # and / at the end to signify it's a directory.
    (r"(^|/)build/", "Build output directory", True),
    (r"(^|/)dist/", "Distribution directory", True),
    (r"(^|/)target/", "Build target directory (e.g., Java/Rust)", True),
    (r"(^|/)bin/", "Binary output directory (heuristic)", True),
    (r"(^|/)obj/", "Object file directory (heuristic)", True),
    (r"(^|/)node_modules/", "Node.js dependencies directory", True),
    (r"(^|/)\.yarn/", "Yarn PnP directory/cache", True),
    (r"(^|/)__pycache__/", "Python bytecode cache directory", True),
    (r"(^|/)\.idea/", "JetBrains IDE project files", True),
    (r"(^|/)\.vscode/", "VS Code editor project files", True),
    (r"\.project$", "Eclipse project file", False), # File specific
    (r"\.classpath$", "Eclipse classpath file", False), # File specific
    (r"(^|/)\.settings/", "Eclipse settings directory", True),
    (r"(^|/)venv/", "Python virtual environment directory", True),
    (r"(^|/)env/", "Python virtual environment directory", True),
    (r"\.env$", "Environment configuration file (often local)", False), # File specific, .env
    (r"(^|/)\.venv/", "Python virtual environment directory", True),
    (r"(^|/)(.*\.egg-info)/", "Python egg info directory", True), # Matches a directory ending in .egg-info

    # Archives (less common to ignore all, but sometimes specific ones) - these are file patterns
    (r"\.zip$", "ZIP archive (check if build artifact)", False),
    (r"\.tar\.gz$", "TGZ archive (check if build artifact)", False),
    (r"\.tgz$", "TGZ archive (check if build artifact)", False),
    (r"\.jar$", "Java archive (check if build artifact or dependency)", False),
    (r"\.war$", "Java web archive (check if build artifact)", False),

    # IDE specific / OS specific
    (r"desktop\.ini$", "Windows desktop configuration file", False), # File specific
    (r"(^|/)\.Trash/", "Trash directory", True),
    (r"(^|/)\.Spotlight-V100/", "macOS Spotlight index", True),
    (r"(^|/)\.fseventsd/", "macOS file system events log", True),
]

def suggest_files_to_ignore(filename_with_path, file_infos):
    """
    Analyzes a file path and suggests if it should be ignored.
    Returns (is_suggested_to_ignore, suggestion_reason)
    file_infos can be used if we need to know if a path is a directory (not directly available from commit files list)
    For now, we rely on patterns that include directory markers like trailing slashes or specific names.
    """
    for pattern_str, reason, is_dir_pattern in UNNECESSARY_FILE_PATTERNS:
        # For directory patterns, we want to match if the path contains that directory component.
        # Example: pattern_str "node_modules/" should match "path/to/node_modules/file.js"
        # Example: pattern_str ".yarn/" should match ".yarn/cache/file.zip" or "project/.yarn/patch.js"
        # We compile the pattern string to a regex object for matching.
        try:
            # Ensure directory patterns correctly match directory structures.
            # A common way is to check if the path contains `(^|/)pattern_as_dir_name($|/)`.
            # The patterns in UNNECESSARY_FILE_PATTERNS are already designed with this in mind (e.g. r"(^|/)node_modules/")
            regex = re.compile(pattern_str)
        except re.error as e:
            # Handle invalid regex patterns if any, though they should be pre-validated
            print(f"Warning: Invalid regex pattern '{pattern_str}': {e}")
            continue

        if regex.search(filename_with_path):
            return True, reason

    return False, ""


@app.route('/', methods=['GET', 'POST'])
def index():
    error = None
    repo_url = request.form.get('repo_url') if request.method == 'POST' else request.args.get('repo_url', '')
    pat = request.form.get('pat') if request.method == 'POST' else request.args.get('pat', '')
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

                headers = {'Accept': 'application/vnd.github.v3+json'}
                if pat:
                    headers['Authorization'] = f'token {pat}'

                response = requests.get(api_url, headers=headers)
                response.raise_for_status()
                branches_data = response.json()

                if not branches_data:
                    error = "No branches found. Repository might be empty, URL invalid, or token lacks permissions for private repo."

                for branch_data in branches_data:
                    branches.append({
                        'name': branch_data['name'],
                        'sha': branch_data['commit']['sha']
                    })

            except ValueError as ve:
                error = str(ve)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    error = "Repository not found. Check URL. If private, ensure PAT is valid and has 'repo' scope."
                elif e.response.status_code == 401:
                    error = "Authentication failed. Provided PAT may be invalid or expired."
                elif e.response.status_code == 403:
                     error = "Access forbidden. PAT may lack necessary permissions (e.g. 'repo' scope) or you've hit a rate limit."
                else:
                    error = f"Error fetching branches ({e.response.status_code}): {e}"
            except requests.exceptions.RequestException as e:
                error = f"Network error fetching branches: {e}"
            except Exception as e:
                error = f"An unexpected error occurred: {e}"

    return render_template('index.html', error=error, repo_url=repo_url, branches=branches, pat=pat)


@app.route('/commits_for_branch', methods=['GET', 'POST'])
def commits_for_branch():
    pat = ''
    if request.method == 'POST':
        repo_url = request.form.get('repo_url')
        branch_name = request.form.get('branch_name')
        pat = request.form.get('pat')
    else: # GET request
        repo_url = request.args.get('repo_url')
        branch_name = request.args.get('branch_name')
        pat = request.args.get('pat')

    commits = []
    error = None

    if not repo_url or not branch_name:
        error = "Repository URL and branch name are required."
        return render_template('index.html', error=error, repo_url=repo_url, branches=[], pat=pat)

    try:
        parts = repo_url.strip('/').split('/')
        user, repo = parts[-2], parts[-1]
        api_url = f"https://api.github.com/repos/{user}/{repo}/commits?sha={branch_name}"

        headers = {'Accept': 'application/vnd.github.v3+json'}
        if pat:
            headers['Authorization'] = f'token {pat}'

        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        commits_data = response.json()

        for commit_data in commits_data[:30]:
            commits.append({
                'sha': commit_data['sha'],
                'message': commit_data['commit']['message'].splitlines()[0],
                'author': commit_data['commit']['author']['name'],
                'date': commit_data['commit']['author']['date']
            })
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            error = f"Commits not found for branch '{branch_name}'. Check repo/branch. If private, ensure PAT is valid."
        elif e.response.status_code == 401:
            error = "Authentication failed for fetching commits. PAT may be invalid."
        elif e.response.status_code == 403:
            error = "Access forbidden for fetching commits. PAT may lack permissions or rate limit hit."
        else:
            error = f"Error fetching commits ({e.response.status_code}): {e}"
    except requests.exceptions.RequestException as e:
        error = f"Network error fetching commits: {e}"
    except Exception as e:
        error = f"An unexpected error occurred: {e}"

    return render_template('index.html', repo_url=repo_url, selected_branch_name=branch_name, commits=commits, error=error, pat=pat)


@app.route('/select_commit', methods=['GET', 'POST'])
def select_commit():
    branch_name = None
    pat = ''
    if request.method == 'POST':
        repo_url = request.form.get('repo_url')
        commit_sha = request.form.get('commit_sha')
        branch_name = request.form.get('branch_name')
        pat = request.form.get('pat')
    else: # GET request
        repo_url = request.args.get('repo_url')
        commit_sha = request.args.get('commit_sha')
        branch_name = request.args.get('branch_name')
        pat = request.args.get('pat')

    files = []
    error = None

    if not repo_url or not commit_sha:
        error = "Repository URL or Commit SHA missing."
        return render_template('index.html', error=error, repo_url=repo_url, selected_branch_name=branch_name, pat=pat)

    try:
        parts = repo_url.strip('/').split('/')
        if len(parts) < 2:
            raise ValueError("Invalid GitHub repository URL format.")
        user, repo = parts[-2], parts[-1]

        api_url = f"https://api.github.com/repos/{user}/{repo}/commits/{commit_sha}"
        headers = {'Accept': 'application/vnd.github.v3+json'}
        if pat:
            headers['Authorization'] = f'token {pat}'

        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        commit_data = response.json()

        current_file_list_for_suggestion = []
        if 'files' in commit_data:
             for file_info in commit_data['files']:
                current_file_list_for_suggestion.append(file_info['filename']) # Used by suggest_files_to_ignore

        for file_info in commit_data.get('files', []): # Use .get for safety
            is_suggested, reason = suggest_files_to_ignore(file_info['filename'], current_file_list_for_suggestion)
            files.append({
                'filename': file_info['filename'],
                'status': file_info['status'],
                'is_suggested_to_ignore': is_suggested,
                'suggestion_reason': reason
            })

        # Fallback if 'files' isn't in commit_data (e.g. merge commits sometimes don't list files this way)
        if not files and 'commit' in commit_data and 'tree' in commit_data['commit']:
            tree_sha = commit_data['commit']['tree']['sha']
            tree_api_url = f"https://api.github.com/repos/{user}/{repo}/git/trees/{tree_sha}?recursive=1"
            tree_response = requests.get(tree_api_url, headers=headers) # Use headers with PAT here too
            tree_response.raise_for_status()
            tree_data = tree_response.json()

            current_tree_paths = [item['path'] for item in tree_data.get('tree', []) if item['type'] == 'blob']

            if 'tree' in tree_data:
                for item in tree_data['tree']:
                    if item['type'] == 'blob':
                        is_suggested, reason = suggest_files_to_ignore(item['path'], current_tree_paths)
                        files.append({
                            'filename': item['path'],
                            'status': 'unknown',
                            'is_suggested_to_ignore': is_suggested,
                            'suggestion_reason': reason
                        })
    except ValueError as ve:
        error = str(ve)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            error = "Commit details not found. Check URL/SHA. If private, ensure PAT is valid."
        elif e.response.status_code == 401:
            error = "Authentication failed for fetching commit details. PAT may be invalid."
        elif e.response.status_code == 403:
            error = "Access forbidden for fetching commit details. PAT may lack permissions or rate limit hit."
        else:
            error = f"Error fetching commit details ({e.response.status_code}): {e}"
    except requests.exceptions.RequestException as e:
        error = f"Network error fetching commit details: {e}"
    except Exception as e:
        error = f"An unexpected error occurred while fetching files: {e}"

    return render_template('commit_files.html',
                           repo_url=repo_url,
                           commit_sha=commit_sha,
                           files=files,
                           error=error,
                           branch_name=branch_name,
                           pat=pat)

@app.route('/process_files', methods=['POST'])
def process_files():
    repo_url = request.form.get('repo_url')
    commit_sha = request.form.get('commit_sha')
    branch_name = request.form.get('branch_name')
    pat = request.form.get('pat') # Get PAT
    selected_files = request.form.getlist('selected_files')

    if not repo_url or not commit_sha:
        return "Error: Missing repository URL or commit SHA.", 400

    commit_files_for_template = []
    if not selected_files:
        # Re-fetch files for the template if none selected (simplified)
        # This part should also use PAT if available for private repos
        try:
            parts = repo_url.strip('/').split('/')
            user, repo = parts[-2], parts[-1]
            api_url = f"https://api.github.com/repos/{user}/{repo}/commits/{commit_sha}"
            headers = {'Accept': 'application/vnd.github.v3+json'}
            if pat:
                headers['Authorization'] = f'token {pat}'
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            commit_data = response.json()

            current_file_list_for_suggestion = []
            if 'files' in commit_data:
                 for file_info in commit_data['files']:
                    current_file_list_for_suggestion.append(file_info['filename'])

            for file_info in commit_data.get('files', []):
                is_suggested, reason = suggest_files_to_ignore(file_info['filename'], current_file_list_for_suggestion)
                commit_files_for_template.append({
                    'filename': file_info['filename'],
                    'status': file_info['status'],
                    'is_suggested_to_ignore': is_suggested,
                    'suggestion_reason': reason
                    })

            if not commit_files_for_template and 'commit' in commit_data and 'tree' in commit_data['commit']: # Fallback
                tree_sha = commit_data['commit']['tree']['sha']
                tree_api_url = f"https://api.github.com/repos/{user}/{repo}/git/trees/{tree_sha}?recursive=1"
                tree_response = requests.get(tree_api_url, headers=headers)
                tree_response.raise_for_status()
                tree_data = tree_response.json()
                current_tree_paths = [item['path'] for item in tree_data.get('tree', []) if item['type'] == 'blob']
                if 'tree' in tree_data:
                    for item in tree_data['tree']:
                        if item['type'] == 'blob':
                            is_suggested, reason = suggest_files_to_ignore(item['path'], current_tree_paths)
                            commit_files_for_template.append({
                                'filename': item['path'],
                                'status': 'unknown',
                                'is_suggested_to_ignore': is_suggested,
                                'suggestion_reason': reason
                                })
        except Exception as e:
            # Log error e
            pass

        error_message = "No files were selected. Please select at least one file."
        return render_template('commit_files.html',
                               repo_url=repo_url,
                               commit_sha=commit_sha,
                               files=commit_files_for_template,
                               error=error_message,
                               branch_name=branch_name,
                               pat=pat)

    gitignore_entries = []
    if selected_files:
        for file_path in selected_files:
            gitignore_entries.append(file_path)
            if '.' in file_path:
                ext = file_path.split('.')[-1]
                if ext and not f"*.{ext}" in gitignore_entries:
                    gitignore_entries.append(f"*.{ext}")

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
                           branch_name=branch_name,
                           pat=pat)


if __name__ == '__main__':
    app.run(debug=True)
