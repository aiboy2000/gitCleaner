from flask import Flask, render_template, request
import requests
import re # For regex matching of file patterns

app = Flask(__name__)

# Define heuristics for identifying unnecessary files - Japanese Reasons
# List of (regex_pattern, reason_string_jp, is_dir_pattern)
UNNECESSARY_FILE_PATTERNS = [
    (r"\.log$", "ログファイル", False),
    (r"\.tmp$", "一時ファイル", False),
    (r"\.temp$", "一時ファイル", False),
    (r"\.bak$", "バックアップファイル", False),
    (r"\.swp$", "スワップファイル", False),
    (r"\.swo$", "スワップファイル", False),
    (r"~$", "バックアップファイル (チルダ)", False),
    (r"\.DS_Store$", "macOS固有のメタデータファイル", False),
    (r"Thumbs\.db$", "Windows固有のメタデータファイル", False),
    (r"\.cache$", "キャッシュファイル", False),
    (r"\.coverage$", "コードカバレッジデータ", False),

    # Compiled files
    (r"\.o$", "コンパイル済みオブジェクトファイル", False),
    (r"\.obj$", "コンパイル済みオブジェクトファイル", False),
    (r"\.class$", "Javaコンパイル済みクラスファイル", False),
    (r"\.pyc$", "Pythonコンパイル済みバイトコードファイル", False),
    (r"\.dll$", "ダイナミックリンクライブラリ (ビルド出力)", False),
    (r"\.so$", "共有オブジェクトファイル (ビルド出力)", False),
    (r"\.exe$", "実行可能ファイル (ビルド出力)", False),
    (r"\.out$", "出力ファイル (ビルド/コンパイラ出力)", False),
    (r"\.app$", "macOSアプリケーションバンドル (ビルド出力)", True),

    # Build directories / Package manager directories
    (r"(^|/)build/", "ビルド出力ディレクトリ", True),
    (r"(^|/)dist/", "配布用ディレクトリ", True),
    (r"(^|/)target/", "ビルドターゲットディレクトリ (例: Java/Rust)", True),
    (r"(^|/)bin/", "バイナリ出力ディレクトリ (ヒューリスティック)", True),
    (r"(^|/)obj/", "オブジェクトファイルディレクトリ (ヒューリスティック)", True),
    (r"(^|/)node_modules/", "Node.js 依存関係ディレクトリ", True),
    (r"(^|/)\.yarn/", "Yarn PnP ディレクトリ/キャッシュ", True),
    (r"(^|/)__pycache__/", "Python バイトコードキャッシュディレクトリ", True),
    (r"(^|/)\.idea/", "JetBrains IDE プロジェクトファイル", True),
    (r"(^|/)\.vscode/", "VS Code エディタプロジェクトファイル", True),
    (r"\.project$", "Eclipse プロジェクトファイル", False),
    (r"\.classpath$", "Eclipse クラスパスファイル", False),
    (r"(^|/)\.settings/", "Eclipse 設定ディレクトリ", True),
    (r"(^|/)venv/", "Python 仮想環境ディレクトリ", True),
    (r"(^|/)env/", "Python 仮想環境ディレクトリ", True),
    (r"\.env$", "環境設定ファイル (ローカル用)", False),
    (r"(^|/)\.venv/", "Python 仮想環境ディレクトリ", True),
    (r"(^|/)(.*\.egg-info)/", "Python egg情報ディレクトリ", True),

    # Archives
    (r"\.zip$", "ZIPアーカイブ (ビルド成果物か確認)", False),
    (r"\.tar\.gz$", "TGZアーカイブ (ビルド成果物か確認)", False),
    (r"\.tgz$", "TGZアーカイブ (ビルド成果物か確認)", False),
    (r"\.jar$", "Javaアーカイブ (ビルド成果物/依存関係か確認)", False),
    (r"\.war$", "Java Webアーカイブ (ビルド成果物か確認)", False),

    # IDE specific / OS specific
    (r"desktop\.ini$", "Windowsデスクトップ設定ファイル", False),
    (r"(^|/)\.Trash/", "ゴミ箱ディレクトリ", True),
    (r"(^|/)\.Spotlight-V100/", "macOS Spotlightインデックス", True),
    (r"(^|/)\.fseventsd/", "macOSファイルシステムイベントログ", True),
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
            error = "リポジトリURLが必要です。"
        else:
            try:
                parts = repo_url.strip('/').split('/')
                if len(parts) < 2 or parts[-2] == '' or parts[-1] == '':
                    raise ValueError("無効なGitHubリポジトリURL形式です。")

                user, repo = parts[-2], parts[-1]
                api_url = f"https://api.github.com/repos/{user}/{repo}/branches"

                headers = {'Accept': 'application/vnd.github.v3+json'}
                if pat:
                    headers['Authorization'] = f'token {pat}'

                response = requests.get(api_url, headers=headers)
                response.raise_for_status()
                branches_data = response.json()

                if not branches_data:
                    error = "ブランチが見つかりません。リポジトリが空であるか、URLが無効であるか、プライベートリポジトリのトークンに権限がない可能性があります。"

                for branch_data in branches_data:
                    branches.append({
                        'name': branch_data['name'],
                        'sha': branch_data['commit']['sha']
                    })

            except ValueError as ve:
                error = str(ve)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    error = "リポジトリが見つかりません。URLを確認してください。プライベートの場合は、PATが有効で 'repo' スコープがあることを確認してください。"
                elif e.response.status_code == 401:
                    error = "認証に失敗しました。提供されたPATが無効であるか、期限切れの可能性があります。"
                elif e.response.status_code == 403:
                     error = "アクセスが禁止されています。PATに必要な権限がない (例: 'repo' スコープ) か、レート制限に達した可能性があります。"
                else:
                    error = f"ブランチの取得中にエラーが発生しました ({e.response.status_code}): {e}"
            except requests.exceptions.RequestException as e:
                error = f"ブランチ取得中のネットワークエラー: {e}"
            except Exception as e:
                error = f"予期せぬエラーが発生しました: {e}"

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
        error = "リポジトリURLとブランチ名が必要です。"
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
            error = f"ブランチ '{branch_name}' のコミットが見つかりません。リポジトリ/ブランチを確認してください。プライベートの場合は、PATが有効であることを確認してください。"
        elif e.response.status_code == 401:
            error = "コミット取得時の認証に失敗しました。PATが無効である可能性があります。"
        elif e.response.status_code == 403:
            error = "コミット取得時のアクセスが禁止されています。PATに権限がないか、レート制限に達した可能性があります。"
        else:
            error = f"コミット取得エラー ({e.response.status_code}): {e}"
    except requests.exceptions.RequestException as e:
        error = f"コミット取得時のネットワークエラー: {e}"
    except Exception as e:
        error = f"予期せぬエラーが発生しました: {e}"

    fetched_branches = []
    if repo_url:
        try:
            parts_b = repo_url.strip('/').split('/')
            user_b, repo_b = parts_b[-2], parts_b[-1]
            api_url_b = f"https://api.github.com/repos/{user_b}/{repo_b}/branches"
            headers_b = {'Accept': 'application/vnd.github.v3+json'}
            if pat:
                headers_b['Authorization'] = f'token {pat}'
            response_b = requests.get(api_url_b, headers=headers_b)
            response_b.raise_for_status()
            for branch_data in response_b.json():
                fetched_branches.append({
                    'name': branch_data['name'],
                    'sha': branch_data['commit']['sha']
                })
        except Exception as e_b:
            print(f"commits_for_branchでのブランチ再取得エラー: {e_b}")
            if not error:
                 error = "ブランチセレクタを表示するためにブランチを再取得できませんでした。コミットリストは正確な場合があります。"


    return render_template('index.html',
                           repo_url=repo_url,
                           selected_branch_name=branch_name,
                           commits=commits,
                           branches=fetched_branches,
                           error=error,
                           pat=pat)


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
        error = "リポジトリURLまたはコミットSHAがありません。"
        return render_template('index.html', error=error, repo_url=repo_url, selected_branch_name=branch_name, pat=pat)

    try:
        parts = repo_url.strip('/').split('/')
        if len(parts) < 2:
            raise ValueError("無効なGitHubリポジトリURL形式です。")
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
            files.append({
                'filename': file_info['filename'],
                'status': file_info['status'],
                'is_suggested_to_ignore': is_suggested,
                'suggestion_reason': reason
            })

        if not files and 'commit' in commit_data and 'tree' in commit_data['commit']:
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
                        files.append({
                            'filename': item['path'],
                            'status': '不明',
                            'is_suggested_to_ignore': is_suggested,
                            'suggestion_reason': reason
                        })
    except ValueError as ve:
        error = str(ve)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            error = "コミット詳細が見つかりません。URL/SHAを確認してください。プライベートの場合は、PATが有効であることを確認してください。"
        elif e.response.status_code == 401:
            error = "コミット詳細取得時の認証に失敗しました。PATが無効である可能性があります。"
        elif e.response.status_code == 403:
            error = "コミット詳細取得時のアクセスが禁止されています。PATに権限がないか、レート制限に達した可能性があります。"
        else:
            error = f"コミット詳細取得エラー ({e.response.status_code}): {e}"
    except requests.exceptions.RequestException as e:
        error = f"コミット詳細取得時のネットワークエラー: {e}"
    except Exception as e:
        error = f"ファイル取得中に予期せぬエラーが発生しました: {e}"

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
    pat = request.form.get('pat')
    selected_files = request.form.getlist('selected_files')

    if not repo_url or not commit_sha:
        return "エラー: リポジトリURLまたはコミットSHAがありません。", 400

    commit_files_for_template = []
    if not selected_files:
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

            if not commit_files_for_template and 'commit' in commit_data and 'tree' in commit_data['commit']:
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
                                'status': '不明',
                                'is_suggested_to_ignore': is_suggested,
                                'suggestion_reason': reason
                                })
        except Exception as e:
            pass

        error_message = "ファイルが選択されていません。少なくとも1つのファイルを選択してください。"
        return render_template('commit_files.html',
                               repo_url=repo_url,
                               commit_sha=commit_sha,
                               files=commit_files_for_template,
                               error=error_message,
                               branch_name=branch_name,
                               pat=pat)

    # Refined .gitignore entries generation
    from collections import defaultdict
    final_rules = set()
    rule_examples = defaultdict(list)

    # Define these directly for clarity in this logic block
    # These are the .gitignore rules we'd prefer for certain directories
    # (regex_to_match_filepath, actual_gitignore_rule_for_dir)
    CONSOLIDATED_DIR_RULES_MAP = {
        r"(^|/)node_modules/": "node_modules/",
        r"(^|/)\.yarn/": ".yarn/",
        r"(^|/)build/": "build/",
        r"(^|/)dist/": "dist/",
        r"(^|/)target/": "target/",
        r"(^|/)__pycache__/": "__pycache__/",
        r"(^|/)\.idea/": ".idea/",
        r"(^|/)\.vscode/": ".vscode/", # Note: .vscode/launch.json is often committed, but settings.json might be ignored.
                                     # For now, if anything in .vscode is selected, suggest ignoring the whole dir.
        r"(^|/)\.settings/": ".settings/",
        r"(^|/)venv/": "venv/",
        r"(^|/)env/": "env/",
        r"(^|/)\.venv/": ".venv/",
        r"(^|/)(.*\.egg-info)/": "*.egg-info/", # More general rule for .egg-info
    }

    # Define common wildcardable extensions
    COMMON_WILDCARD_EXTENSIONS = {".log", ".tmp", ".temp", ".bak", ".o", ".obj", ".class", ".pyc", ".swp", ".swo", ".cache", ".coverage"}


    if selected_files:
        for file_path in selected_files:
            original_file_path_for_example = file_path # Keep original for comments
            processed_for_this_file = False

            # 1. Check against General Directory Rules
            for dir_regex, dir_rule in CONSOLIDATED_DIR_RULES_MAP.items():
                if re.search(dir_regex, file_path):
                    final_rules.add(dir_rule)
                    rule_examples[dir_rule].append(original_file_path_for_example)
                    processed_for_this_file = True
                    break
            if processed_for_this_file:
                continue

            # 2. Check for Common Wildcardable Extensions
            file_extension = None
            if '.' in file_path:
                potential_ext = "." + file_path.split('.')[-1]
                # Check against double extensions like .tar.gz
                for double_ext_candidate in [".tar.gz", ".tar.bz2", ".tar.xz"]: # Add more if needed
                    if file_path.endswith(double_ext_candidate):
                        potential_ext = double_ext_candidate
                        break

                if potential_ext in COMMON_WILDCARD_EXTENSIONS:
                    file_extension = potential_ext # e.g. ".log", ".bak"

            if file_extension:
                wildcard_rule = f"*{file_extension}" # e.g. "*.log"
                final_rules.add(wildcard_rule)
                rule_examples[wildcard_rule].append(original_file_path_for_example)
                processed_for_this_file = True
                continue

            # 3. If not covered by above, add the specific file path
            if not processed_for_this_file:
                final_rules.add(original_file_path_for_example)
                # No examples needed if the rule is the file itself.

    # Construct gitignore_entries list for the template
    gitignore_entries = []
    sorted_final_rules = sorted(list(final_rules))

    for rule in sorted_final_rules:
        gitignore_entries.append(rule)
        if rule in rule_examples:
            for example_file in sorted(list(set(rule_examples[rule]))): # Sort examples and ensure unique
                # Only add example if it's different from the rule itself (for specific file rules)
                # and if the rule isn't a direct match for the example (e.g. rule is file path itself)
                if example_file != rule :
                    gitignore_entries.append(f"# {example_file} (covered by {rule})")

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
            f"# 3. Set up the 'origin' remote to point to your original repository URL:\n"
            f"#    (Mirrored clones often don't have 'origin' set up by default for pushing)\n"
            f"git remote add origin {repo_url}\n"
            f"#    You can verify with: git remote -v\n\n"
            f"# 4. Ensure you have git-filter-repo installed (e.g., pip install git-filter-repo).\n\n"
            f"# 5. Run git filter-repo to remove the selected files from the history of branch '{branch_name}':\n"
            f"#    (This command removes the files. Use with extreme caution!)\n"
            f"git filter-repo --refs {branch_name} --invert-paths {filter_repo_paths_options}\n\n"
            f"# 6. Inspect your repository and branch '{branch_name}' to ensure the changes are correct.\n"
            f"#    For example, check commit history and file contents for this branch.\n\n"
            f"# 7. If satisfied, force push the changes for branch '{branch_name}' to your 'origin' remote:\n"
            f"#    WARNING: This overwrites history on the remote for branch '{branch_name}'.\n"
            f"#    Ensure all collaborators using this branch are aware.\n"
            f"git push origin --force {branch_name}\n\n"
            f"# IMPORTANT NOTES:\n"
            f"# - ALWAYS BACKUP YOUR ORIGINAL REPOSITORY BEFORE PERFORMING THESE ACTIONS.\n"
            f"# - This command targets ONLY the branch '{branch_name}'. The files will remain in the history of other branches.\n"
            f"# - If other branches were created from '{branch_name}' *before* this cleaning, they will still contain the files.\n"
            f"# - Merging this cleaned branch into other un-cleaned branches later might reintroduce the files or cause conflicts.\n"
            f"# - To remove files from ALL history, remove `--refs {branch_name}` from the filter-repo command \n"
            f"#   and use `git push origin --force --all` and `git push origin --force --tags` (after careful review)."
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
