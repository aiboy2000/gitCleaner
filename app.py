from flask import Flask, render_template, request
import requests

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    commits = []
    error = None
    repo_url = ''
    if request.method == 'POST':
        repo_url = request.form['repo_url']
        try:
            # Basic validation and parsing of URL
            parts = repo_url.strip('/').split('/')
            if len(parts) < 2 or parts[-2] == '' or parts[-1] == '':
                raise ValueError("Invalid GitHub repository URL format.")

            user, repo = parts[-2], parts[-1]
            api_url = f"https://api.github.com/repos/{user}/{repo}/commits"
            response = requests.get(api_url)
            response.raise_for_status() # Raise an exception for HTTP errors
            commits_data = response.json()

            # Limit to a reasonable number of commits, e.g., latest 30
            for commit_data in commits_data[:30]:
                commits.append({
                    'sha': commit_data['sha'],
                    'message': commit_data['commit']['message'].splitlines()[0], # First line of message
                    'author': commit_data['commit']['author']['name'],
                    'date': commit_data['commit']['author']['date']
                })
        except ValueError as ve:
            error = str(ve)
        except requests.exceptions.RequestException as e:
            error = f"Error fetching commits: {e}"
        except Exception as e:
            error = f"An unexpected error occurred: {e}"

    return render_template('index.html', commits=commits, error=error, repo_url=repo_url)

@app.route('/select_commit', methods=['POST'])
def select_commit():
    repo_url = request.form.get('repo_url')
    commit_sha = request.form.get('commit_sha')
    files = []
    error = None

    if not repo_url or not commit_sha:
        error = "Repository URL or Commit SHA missing."
        return render_template('index.html', error=error) # Or a dedicated error page

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
                           error=error)

@app.route('/process_files', methods=['POST'])
def process_files():
    repo_url = request.form.get('repo_url')
    commit_sha = request.form.get('commit_sha')
    selected_files = request.form.getlist('selected_files')

    if not repo_url or not commit_sha:
        # Handle error, maybe redirect to index or show an error message
        return "Error: Missing repository URL or commit SHA.", 400

    if not selected_files:
        # Handle case where no files are selected, maybe redirect back or show a message
        # For now, just return a message.
        # Ideally, you'd re-render the commit_files.html with an error/info message.
        # Fetching files again to re-render:
        # This is a simplified version. You might want to pass the files list
        # or re-fetch if state isn't maintained appropriately.
        error = "No files were selected. Please select at least one file."
        # To properly re-render commit_files.html, you'd need the 'files' list again for that commit.
        # This part is simplified for brevity in this step.
        # A more robust solution would involve re-querying or better state management.
        return render_template('commit_files.html',
                               repo_url=repo_url,
                               commit_sha=commit_sha,
                               files=[], # This should be the actual file list for the commit
                               error=error)


    # In the next steps, we will:
    # 1. Suggest common unnecessary file types from the selected_files.
    #    (This step focuses on user selection, auto-suggestion can be an enhancement)
    # 2. Generate .gitignore entries. (Done in the next step)
    # 3. Generate Git cleanup commands. (Done in a subsequent step)

    # For now, the identification is done by the user checking boxes.
    # We will pass these selected files to a new template/route for further processing.
    # This current step is about allowing the *user* to identify/select.
    # The next step will generate .gitignore entries from these.

    # Redirect to a new page or display results on the same page.
    # For this iteration, let's create a new results page.
    # In a more complex app, you might do this with AJAX or on the same page.

    # Store selected files in session or pass via POST to the next view
    # For simplicity, passing to a new template that will display them and then
    # offer next actions (generate .gitignore, generate commands)

    # This function will now forward to a page that prepares for .gitignore generation
    # and command generation.

    # Placeholder: The actual logic for suggesting unnecessary files based on patterns
    # (e.g., *.log, *.tmp) can be added here or in the template.
    # For this step, we assume user has selected the files they deem unnecessary.

    # The 'process_files' endpoint is now more of an intermediate step.
    # Let's rename/refactor to make it clearer.
    # The form in commit_files.html will now point to a new endpoint
    # that handles the generation of .gitignore rules and cleanup commands.
    # Let's adjust the plan: this step (Identify unnecessary files) means
    # the user selects them. The next step will be "Generate .gitignore and cleanup commands".

    # For now, let's assume 'process_files' is where the user has made their selection.
    # The next step will take these 'selected_files' and generate outputs.
    # So, this step is primarily about enabling the UI for selection, which is done.
    # The logic for "identifying" is simply the user's manual selection.

    # Let's pass the selected files to a new template `results.html`

    # Generate .gitignore entries
    gitignore_entries = []
    if selected_files:
        for file_path in selected_files:
            # Simple case: add the full path.
            # More complex: suggest patterns like *.log if "some.log" is selected.
            # For now, direct mapping.
            gitignore_entries.append(file_path)

            # Suggest wildcard for extensions
            if '.' in file_path:
                ext = file_path.split('.')[-1]
                if ext and not f"*.{ext}" in gitignore_entries:
                    gitignore_entries.append(f"*.{ext}")

    # Generate cleanup command
    # IMPORTANT: Using BFG Repo-Cleaner is recommended over filter-branch for speed and simplicity.
    # git filter-repo is the modern replacement for filter-branch and BFG.
    # Assuming git filter-repo is installed by the user.
    cleanup_command = ""
    if selected_files:
        files_to_remove_str = " ".join([f"'{file}'" for file in selected_files]) # Ensure files with spaces are quoted

        # It's crucial to inform the user about the implications of history rewriting.
        # And that they need to clone a fresh copy --mirror for this.
        # The command provided is a template. User needs to adapt it.

        # Command using git filter-repo
        # User needs to install it: pip install git-filter-repo
        # User should run this in a fresh clone made with --mirror
        # e.g., git clone --mirror https://github.com/user/repo.git repo.git-mirror
        # cd repo.git-mirror
        # git filter-repo --invert-paths --paths-from-files <(printf "path1\npath2")
        # or for specific files:
        # git filter-repo --path file1 --path dir/file2 --invert-paths
        #
        # Simpler approach: provide the list of files and let user construct the command,
        # or use a simpler tool if possible.
        #
        # For this step, we will generate a `git filter-repo` command.
        # It's powerful but requires user understanding.

        filter_repo_paths_options = " ".join([f"--path \"{file}\"" for file in selected_files])

        cleanup_command = (
            f"# Make a fresh clone: git clone --mirror {repo_url} {repo_url.split('/')[-1]}.git-mirror\n"
            f"# cd into it: cd {repo_url.split('/')[-1]}.git-mirror\n"
            f"# Ensure you have git-filter-repo installed (pip install git-filter-repo)\n"
            f"# To remove the selected files from the history of *all* branches and tags:\n"
            f"git filter-repo --invert-paths {filter_repo_paths_options}\n\n"
            f"# If you only want to remove files from the specific commit ({commit_sha[:7]}) and its descendants,\n"
            f"# that's more complex and typically involves interactive rebase or more targeted filter-repo usage.\n"
            f"# The command above is a common use case for cleaning entire history.\n"
            f"# ALWAYS BACKUP YOUR REPOSITORY BEFORE REWRITING HISTORY.\n"
            f"# After running, force push: git push origin --force --all && git push origin --force --tags"
        )
        # Note: Removing from a *single* specific commit without affecting others, while possible,
        # is very advanced (e.g. replace commit with a new one via rebase -i and then filter-branch/filter-repo on a temporary branch).
        # The most common request is to remove files from history going forward.
        # The generated command aims for removing files from all history.

    return render_template('results.html',
                           repo_url=repo_url,
                           commit_sha=commit_sha,
                           selected_files=selected_files,
                           gitignore_entries=gitignore_entries,
                           cleanup_command=cleanup_command)


if __name__ == '__main__':
    app.run(debug=True)
