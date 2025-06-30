from flask import Flask, render_template, request
import requests

app = Flask(__name__)

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


@app.route('/commits_for_branch', methods=['POST'])
def commits_for_branch():
    repo_url = request.form.get('repo_url')
    branch_name = request.form.get('branch_name')
    commits = []
    error = None

    if not repo_url or not branch_name:
        error = "Repository URL and branch name are required."
        # Redirect or render with error, potentially back to index or a specific error page
        return render_template('index.html', error=error, repo_url=repo_url) # Simplified error handling

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
                files.append({
                    'filename': file_info['filename'],
                    'status': file_info['status'], # e.g., 'added', 'modified', 'removed'
                    # We might not get raw_url directly here for all files easily,
                    # but filename is the primary need for .gitignore
                })
        else:
            # If 'files' is not in commit_data, it might be an older commit or an issue with the API response
            # Fallback: try to get the tree for this commit
            tree_sha = commit_data['commit']['tree']['sha']
            tree_api_url = f"https://api.github.com/repos/{user}/{repo}/git/trees/{tree_sha}?recursive=1"
            tree_response = requests.get(tree_api_url)
            tree_response.raise_for_status()
            tree_data = tree_response.json()
            if 'tree' in tree_data:
                for item in tree_data['tree']:
                    if item['type'] == 'blob': # We are interested in files (blobs)
                        files.append({
                            'filename': item['path'],
                            'status': 'unknown' # Status isn't directly available from tree view like this
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
