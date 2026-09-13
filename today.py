import datetime
import layout
import requests
import os
from lxml import etree
import time
import hashlib
import base64
import tempfile

# Fine-grained personal access token with All Repositories access:
# Account permissions: read:Followers, read:Starring, read:Watching
# Repository permissions: read:Commit statuses, read:Contents, read:Issues, read:Metadata, read:Pull Requests
# Issues and pull requests permissions not needed at the moment, but may be used in the future
HEADERS = {'authorization': 'token '+ os.environ['ACCESS_TOKEN']}
USER_NAME = os.environ['USER_NAME'] # 'Andrew6rant'
QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0, 'recursive_loc': 0, 'graph_commits': 0, 'loc_query': 0}

# The per-repo stats live in a PRIVATE repo, not this one. This repo is public, so a file
# here listing every repository the author touches -- with daily per-repo commit and line
# churn -- discloses an employer's private project names and activity. Keyed by plaintext
# name in the private ledger so it stays readable years later; sha256 would be one-way.
CACHE_REPO = os.environ.get('CACHE_REPO', '')
LEDGER_PATH = 'ledger.txt'
# Materialised OUTSIDE the repo tree: the workflow's `git add` can then never see it,
# which makes the privacy guarantee structural instead of a rule someone has to remember.
CACHE_FILE = os.path.join(os.environ.get('RUNNER_TEMP') or tempfile.gettempdir(),
                          'readme-stats-' + hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()[:16] + '.txt')
REPO_META = {} # sha256(nameWithOwner) -> (nameWithOwner, is_private, owner_login)
FORMATTER_LINES = 0 # how many timing lines formatter() has printed, for the cursor rewind
BOT_IDENTITY = {'name': 'README-Bot', 'email': 'github-actions[bot]@users.noreply.github.com'}


TRANSIENT_ERROR_TYPES = ('SERVICE_UNAVAILABLE', 'RATE_LIMITED')
TRANSIENT_ERROR_TEXT = ('something went wrong', 'timeout', 'timed out')


def body_problem(request):
    """
    Inspects a 200 response. Returns None if the body is a clean GraphQL answer, otherwise
    (is_transient, summary).

    A 200 is not success. GitHub answers query timeouts and rate limits with 200 plus an
    `errors` array, and can return a non-JSON error page with 200 -- the latter is what
    killed the 2026-09-11 build. Every caller indexes straight into ['data'], so an
    unchecked partial answer reads as a real one. That is how a dead token published
    'Stars: 0' for a month instead of failing.

    The summary carries only error `type` and `path`. Never `message`: it echoes query
    variables, i.e. private repo names, and this repo's Actions logs are world-readable.
    """
    try:
        body = request.json()
    except ValueError:
        return True, f'non-JSON body ({len(request.content)} bytes)'
    errors = body.get('errors')
    if not errors:
        return None
    transient = any(e.get('type') in TRANSIENT_ERROR_TYPES for e in errors) or any(
        text in (e.get('message') or '').lower() for e in errors for text in TRANSIENT_ERROR_TEXT)
    summary = 'errors=[' + ', '.join(
        "{}@{}".format(e.get('type', '?'), '/'.join(str(p) for p in (e.get('path') or []) )) for e in errors) + ']'
    return transient, summary


def simple_request(func_name, query, variables, on_failure=None):
    """
    Returns a request, or raises an Exception if the response does not succeed.
    Retries transient failures: gateway errors (502/503/504), secondary rate limits that
    carry a retry-after header, and 200s whose body is a transient GraphQL error.

    on_failure runs immediately before raising -- recursive_loc uses it to flush the cache
    so a mid-walk crash does not lose the repos already counted.
    """
    for attempt in range(5):
        request = requests.post('https://api.github.com/graphql', json={'query': query, 'variables':variables}, headers=HEADERS)
        if request.status_code == 200:
            problem = body_problem(request)
            if problem is None:
                return request
            transient, summary = problem
            if transient and attempt < 4:
                time.sleep(3 * (attempt + 1)) # back off (3s, 6s, 9s, 12s) then retry
                continue
            if on_failure: on_failure()
            raise Exception(func_name, ' returned a 200 carrying', summary, QUERY_COUNT)
        if request.status_code in (502, 503, 504) and attempt < 4:
            time.sleep(3 * (attempt + 1))
            continue
        # Secondary rate limit (the undocumented anti-abuse limit) answers 403/429 with a
        # retry-after. Only retry when GitHub actually asks us to -- a 403 without it is an
        # auth failure and retrying just delays a real error by minutes.
        if request.status_code in (403, 429) and 'retry-after' in request.headers and attempt < 4:
            time.sleep(min(int(request.headers['retry-after']), 120))
            continue
        break
    if on_failure: on_failure()
    # Never include request.text: this repo is public, so Actions logs are world-readable,
    # and GraphQL error bodies echo query variables (repo names) and partial data.
    raise Exception(func_name, ' has failed with a', request.status_code,
                    f'({len(request.content)} byte body withheld)', QUERY_COUNT)


def graph_commits(created_at, stored_years):
    """
    All-time contributions, plus the per-year figures to store back.

    contributionsCollection accepts at most a one-year window, so all-time means one window
    per calendar year, aliased into a single request -- which costs 1 rate-limit point in
    total no matter how many years accumulate.

    Windows start at January 1st of the account's creation year rather than at createdAt:
    this account has 13 contributions dated before its own creation timestamp, and the
    profile page's year tabs span whole calendar years, so anchoring to createdAt reports a
    smaller number than the profile a reader would compare against.

    Each year is floored at its stored value. Closed years are effectively immutable, but the
    important case is the current one: `restrictedContributionsCount` only counts private
    contributions while the account shares them, and losing access to a private repo can
    retract them. Without a floor the headline number would quietly shrink.
    """
    query_count('graph_commits')
    years = list(range(int(created_at[:4]), datetime.datetime.now(datetime.timezone.utc).year + 1))
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    windows = ' '.join(
        f'y{year}: contributionsCollection(from: "{year}-01-01T00:00:00Z", '
        f'to: "{now if year == years[-1] else f"{year}-12-31T23:59:59Z"}") '
        '{ contributionCalendar { totalContributions } }' for year in years)
    query = 'query($login: String!) { user(login: $login) { ' + windows + ' } }'
    user = simple_request(graph_commits.__name__, query, {'login': USER_NAME}).json()['data']['user']
    per_year = {}
    for year in years:
        live = int(user[f'y{year}']['contributionCalendar']['totalContributions'])
        per_year[str(year)] = max(live, int(stored_years.get(str(year), 0)))
    return sum(per_year.values()), per_year


def graph_repos_stars(count_type, owner_affiliation, cursor=None):
    """
    Uses GitHub's GraphQL v4 API to return my total repository or star count.
    """
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    repositories = request.json()['data']['user']['repositories']
    if count_type == 'repos':
        # totalCount is already the server-side total for every page. Paginating it would
        # add the same number once per page.
        return repositories['totalCount']
    if count_type == 'stars':
        # stars_counter only sees one page, and the query asks for 100 at a time, so past
        # 100 repos the untotalled pages were silently dropped.
        total_stars = stars_counter(repositories['edges'])
        if repositories['pageInfo']['hasNextPage']:
            total_stars += graph_repos_stars('stars', owner_affiliation, repositories['pageInfo']['endCursor'])
        return total_stars
    raise Exception(f'graph_repos_stars(): unknown count_type {count_type!r}')


def recursive_loc(owner, repo_name, data, cache_comment, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    """
    Uses GitHub's GraphQL v4 API and cursor pagination to fetch 100 commits from a repository at a time
    """
    query_count('recursive_loc')
    query = '''
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    ... on Commit {
                                        committedDate
                                    }
                                    author {
                                        user {
                                            id
                                        }
                                    }
                                    deletions
                                    additions
                                }
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
    }'''
    variables = {'repo_name': repo_name, 'owner': owner, 'cursor': cursor}
    # This used to bypass simple_request purely so the cache could be flushed before
    # raising; on_failure does that, so the retry and 200-body checks now apply here too.
    save_progress = lambda: force_close_file(data, cache_comment)
    request = simple_request(recursive_loc.__name__, query, variables, on_failure=save_progress)
    try:
        branch = request.json()['data']['repository']['defaultBranchRef']
        if branch is None: return (0, 0, 0) # Only count commits if repo isn't empty
        history = branch['target']['history']
    except Exception:
        save_progress() # don't lose the repos already walked
        raise
    return loc_counter_one_repo(owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits)


def loc_counter_one_repo(owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits):
    """
    Recursively call recursive_loc (since GraphQL can only search 100 commits at a time) 
    only adds the LOC value of commits authored by me
    """
    for node in history['edges']:
        if node['node']['author']['user'] == OWNER_ID:
            my_commits += 1
            addition_total += node['node']['additions']
            deletion_total += node['node']['deletions']

    if history['edges'] == [] or not history['pageInfo']['hasNextPage']:
        return addition_total, deletion_total, my_commits
    else: return recursive_loc(owner, repo_name, data, cache_comment, addition_total, deletion_total, my_commits, history['pageInfo']['endCursor'])


def loc_query(owner_affiliation, comment_size=0, force_cache=False, cursor=None, edges=None):
    """
    Uses GitHub's GraphQL v4 API to query all the repositories I have access to (with respect to owner_affiliation)
    Queries 60 repos at a time, because larger queries give a 502 timeout error and smaller queries send too many
    requests and also give a 502 error.
    Returns the total number of lines of code in all repositories
    """
    if edges is None: edges = [] # a [] default is shared across calls; a second top-level
                                 # call would accumulate onto the first one's repos
    query_count('loc_query')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
            edges {
                node {
                    ... on Repository {
                        nameWithOwner
                        isPrivate
                        owner {
                            login
                        }
                        defaultBranchRef {
                            target {
                                ... on Commit {
                                    history {
                                        totalCount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(loc_query.__name__, query, variables)
    repositories = request.json()['data']['user']['repositories']
    page = repositories['edges']
    nulls = sum(1 for edge in page if edge['node'] is None)
    if nulls:
        # A null node means totalCount counts a repository the token cannot resolve. Skipping
        # them is what let a mis-scoped token publish 'Stars: 0' and an undercounted LOC for a
        # month. Raise before cache_builder writes anything, so a bad token fails the build
        # instead of quietly shrinking the numbers.
        # There is nothing to name it by -- the whole node is null, so it has no
        # nameWithOwner to report. Count and position are all that exist.
        raise Exception(f'loc_query(): {nulls} of {len(page)} repository nodes came back null '
                        f'after {len(edges)} resolved; the token cannot see some repositories', QUERY_COUNT)
    edges += page
    if repositories['pageInfo']['hasNextPage']:   # If repository data has another page
        return loc_query(owner_affiliation, comment_size, force_cache, repositories['pageInfo']['endCursor'], edges)
    else:
        return cache_builder(edges, comment_size, force_cache)


def cache_builder(edges, comment_size, force_cache, loc_add=0, loc_del=0):
    """
    Checks each repository in edges to see if it has been updated since the last time it was cached
    If it has, run recursive_loc on that repository to update the LOC count
    """
    cached = True # Assume all repositories are cached
    filename = CACHE_FILE
    try:
        with open(filename, 'r') as f:
            data = f.readlines()
    except FileNotFoundError: # If the cache file doesn't exist, create it
        data = []
        if comment_size > 0:
            for _ in range(comment_size): data.append('This line is a comment block. Write whatever you want here.\n')
        with open(filename, 'w') as f:
            f.writelines(data)

    # Only an explicit force_cache wipes the file now. Flushing whenever the repo *count*
    # changed was safe when rows were read positionally, but it is the opposite of what the
    # ledger needs: a repo the token can no longer see would be erased along with its
    # commits and lines. Rows are keyed by hash (see below), so a changed repo set needs no
    # flush -- new repos are appended and repos that disappear simply keep their last known
    # values, which is exactly the durability the ledger exists to provide.
    if force_cache:
        cached = False
        flush_cache(edges, filename, comment_size)
        with open(filename, 'r') as f:
            data = f.readlines()

    cache_comment = data[:comment_size] # save the comment block
    data = data[comment_size:] # remove those lines

    # Index rows by repo hash rather than trusting row order. flush_cache only fires when
    # the repo *count* changes, so deleting one repo and creating another leaves the rows
    # skewed by one: every row after the deleted repo mismatched its edge, failed the hash
    # check, and was then never updated and never reported. Keying by hash removes that
    # silent-staleness class, and is a prerequisite for a name-keyed ledger -- pairing
    # data[index] with edges[index] under a skew would record one repo's LOC and commits
    # under another repo's name.
    row_of = {}
    for i, line in enumerate(data):
        fields = line.split()
        if fields: row_of[fields[0]] = i

    for edge in edges:
        name = edge['node']['nameWithOwner']
        repo_hash = hashlib.sha256(name.encode('utf-8')).hexdigest()
        # Remember the name for the ledger: the cache file is hash-keyed, so this is the only
        # place both the hash and the name are in scope.
        REPO_META[repo_hash] = (name, edge['node']['isPrivate'], edge['node']['owner']['login'])
        index = row_of.get(repo_hash)
        if index is None: # repo is new since the last run; add a row for it
            data.append(repo_hash + ' 0 0 0 0\n')
            index = row_of[repo_hash] = len(data) - 1
            cached = False
        commit_count = data[index].split()[1]

        # An empty repo has no defaultBranchRef. Check it explicitly: the old blanket
        # `except TypeError` wrapped the recursive_loc call too, so any failure inside it
        # (null repository, null commit author, a null node) was swallowed and the repo
        # written as '0 0 0 0' -- zeroing both its commits and its lines of code.
        branch = edge['node']['defaultBranchRef']
        if branch is None:
            data[index] = repo_hash + ' 0 0 0 0\n'
            continue
        live_count = branch['target']['history']['totalCount']
        if int(commit_count) != live_count: # if commit count has changed, update loc for that repo
            owner, repo_name = name.split('/')
            loc = recursive_loc(owner, repo_name, data, cache_comment)
            data[index] = f'{repo_hash} {live_count} {loc[2]} {loc[0]} {loc[1]}\n'
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)
    for line in data:
        loc = line.split()
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, cached]


def flush_cache(edges, filename, comment_size):
    """
    Wipes the cache file
    This is called when the number of repositories changes or when the file is first created
    """
    with open(filename, 'r') as f:
        data = []
        if comment_size > 0:
            data = f.readlines()[:comment_size] # only save the comment
    with open(filename, 'w') as f:
        f.writelines(data)
        for node in edges:
            f.write(hashlib.sha256(node['node']['nameWithOwner'].encode('utf-8')).hexdigest() + ' 0 0 0 0\n')


def ledger_guard():
    """
    Refuses to go any further unless CACHE_REPO is a private repo owned by USER_NAME.

    The ledger holds plaintext private repository names. A typo in the env var, a rename, or
    a repo recreated as public would publish them, so this is checked before the first write
    rather than trusted.
    """
    if not CACHE_REPO:
        raise Exception('CACHE_REPO is unset; refusing to run without the private stats ledger')
    request = requests.get(f'https://api.github.com/repos/{CACHE_REPO}', headers=HEADERS)
    if request.status_code != 200:
        raise Exception('ledger_guard(): cannot read CACHE_REPO', request.status_code)
    info = request.json()
    if not info.get('private'):
        raise Exception('ledger_guard(): CACHE_REPO is NOT private; refusing to write repository names')
    if info['owner']['login'].lower() != USER_NAME.lower():
        raise Exception('ledger_guard(): CACHE_REPO is owned by someone else; refusing to write')


def ledger_load():
    """
    Returns ({name: [commit_count, my_commits, adds, dels, is_private, owner, first, last]}, blob_sha).
    A 404 is the normal first-run path, not an error: the file is created by the first PUT.
    """
    request = requests.get(f'https://api.github.com/repos/{CACHE_REPO}/contents/{LEDGER_PATH}', headers=HEADERS)
    if request.status_code == 404:
        return {}, {}, None
    if request.status_code != 200:
        raise Exception('ledger_load() failed with a', request.status_code)
    body = request.json()
    records, years = {}, {}
    for line in base64.b64decode(body['content']).decode('utf-8').splitlines(): # content is line-wrapped base64
        fields = line.split()
        if len(fields) == 10 and fields[0] == 'repo': # repo <name> + 8 stat fields
            records[fields[1]] = fields[2:]
        elif len(fields) == 3 and fields[0] == 'year': # year <yyyy> <totalContributions>
            years[fields[1]] = fields[2]
    return records, years, body['sha']


def ledger_merge(records, live):
    """
    Folds this run's repos into the ledger. Records are never removed: a repo that drops out
    of `live` is one the token can no longer see -- access revoked, repo deleted, org
    membership ended -- and its commits and lines must keep counting. That is the entire
    point of the ledger.
    """
    today = datetime.date.today().isoformat()
    merged = {name: list(fields) for name, fields in records.items()}
    for name, stats in live.items():
        commit_count, my_commits, adds, dels, is_private, owner = stats
        first_seen = merged[name][6] if name in merged else today
        merged[name] = [str(commit_count), str(my_commits), str(adds), str(dels),
                        'private' if is_private else 'public', owner, first_seen, today]
    return merged


def ledger_save(merged, years, sha):
    """PUTs the ledger. Returns False on a 409 so the caller can re-read and re-merge."""
    lines = ['# Per-repo stats for the GitHub profile card. Never commit this to a public repo.',
             '# repo <nameWithOwner> <commits> <my_commits> <additions> <deletions> <privacy> <owner> <first_seen> <last_seen>',
             '# year <yyyy> <totalContributions>   (high-water marked; never decreases)']
    lines += [' '.join(['repo', name] + merged[name]) for name in sorted(merged)]
    lines += [f'year {year} {years[year]}' for year in sorted(years)]
    payload = {'message': 'chore: update stats ledger',
               'content': base64.b64encode(('\n'.join(lines) + '\n').encode('utf-8')).decode('ascii'),
               'committer': BOT_IDENTITY, 'author': BOT_IDENTITY}
    if sha: payload['sha'] = sha # omitted on create; required on update
    request = requests.put(f'https://api.github.com/repos/{CACHE_REPO}/contents/{LEDGER_PATH}',
                           json=payload, headers=HEADERS)
    if request.status_code in (200, 201):
        return True
    if request.status_code == 409: # stale sha, or a concurrent write
        return False
    # Status only. The request body is the base64 ledger: every private repo name in one line.
    raise Exception('ledger_save() failed with a', request.status_code)


def cache_seed(records, comment_size):
    """
    Writes the local hash-keyed cache file from the name-keyed ledger, so cache_builder,
    and force_close_file keep operating on a plain file exactly as before.
    """
    lines = ['This line is a comment block. Write whatever you want here.\n'] * comment_size
    for name, fields in records.items():
        repo_hash = hashlib.sha256(name.encode('utf-8')).hexdigest()
        REPO_META[repo_hash] = (name, fields[4] == 'private', fields[5])
        lines.append(f'{repo_hash} {fields[0]} {fields[1]} {fields[2]} {fields[3]}\n')
    with open(CACHE_FILE, 'w') as f:
        f.writelines(lines)


def cache_live_rows(comment_size):
    """Reads the cache file back as {name: (commits, my_commits, adds, dels, is_private, owner)}."""
    live = {}
    with open(CACHE_FILE, 'r') as f:
        for line in f.readlines()[comment_size:]:
            fields = line.split()
            if len(fields) != 5:
                continue
            meta = REPO_META.get(fields[0])
            if meta is None:
                continue # hash we never saw a name for this run; the ledger keeps its existing record
            name, is_private, owner = meta
            live[name] = (int(fields[1]), int(fields[2]), int(fields[3]), int(fields[4]), is_private, owner)
    return live


def ledger_sync(live, live_years):
    """Read, merge, write -- retrying the whole cycle if someone else wrote in between."""
    for _ in range(3):
        records, years, sha = ledger_load()
        merged = ledger_merge(records, live)
        # Floor every year at its stored value here too, so a concurrent writer's higher
        # number is never rolled back by this run's re-merge.
        merged_years = dict(years)
        for year, total in live_years.items():
            merged_years[year] = str(max(int(total), int(years.get(year, 0))))
        if len(merged) < len(records):
            raise Exception('ledger_sync(): merge would drop records; refusing to shrink the ledger')
        if merged == records and merged_years == years:
            return merged, False
        if ledger_save(merged, merged_years, sha):
            return merged, True
    raise Exception('ledger_sync(): could not write the ledger after 3 attempts')


def force_close_file(data, cache_comment):
    """
    Forces the file to close, preserving whatever data was written to it
    This is needed because if this function is called, the program would've crashed before the file is properly saved and closed
    """
    filename = CACHE_FILE
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)
    print('There was an error while writing to the cache file. The file,', filename, 'has had the partial data saved and closed.')


def stars_counter(data):
    """
    Count total stars in repositories owned by me
    """
    total_stars = 0
    for node in data:
        if node['node'] is None:
            # This 'continue' used to be the bug: a token that could not resolve any repo
            # made every node null, so the sum was 0 and looked like a real answer. 36 stars
            # were reported as 0 for a month. Same guard as loc_query -- fail, don't skip.
            raise Exception('stars_counter(): a repository node came back null; '
                            'the token cannot see some repositories', QUERY_COUNT)
        total_stars += node['node']['stargazers']['totalCount']
    return total_stars


def svg_overwrite(filename, contributions_data, star_data, repo_data, contrib_data, follower_data, loc_data):
    """
    Parse SVG files and update elements with my contributions, stars, repositories, and
    lines written.

    Every field takes its width from layout.py rather than the magic numbers this used to
    carry, so the '|' separators stay on one column no matter how many digits a value grows
    to. generate_svg.py lays the placeholders out from those same numbers.
    """
    # Entity resolution off: lxml's default would expand a DOCTYPE entity pointing at a local
    # file or URL, and svg_overwrite writes the tree straight back to a file the workflow
    # publishes. Defence in depth -- planting that DOCTYPE needs push access already.
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    tree = etree.parse(filename, parser)
    root = tree.getroot()
    justify_format(root, 'repo_data', repo_data, layout.field_len('Repos', layout.L))
    justify_format(root, 'contrib_data', contrib_data, layout.field_len('Contributed', layout.R))
    justify_format(root, 'contributions_data', contributions_data, layout.field_len('Contributions', layout.L))
    justify_format(root, 'follower_data', follower_data, layout.field_len('Followers', layout.R))
    justify_format(root, 'loc_data', loc_data[2], layout.field_len('Lines of Code', layout.L))
    justify_format(root, 'star_data', star_data, layout.field_len('Stars', layout.R))
    tree.write(filename, encoding='utf-8', xml_declaration=True)


def justify_format(root, element_id, new_text, length=0):
    """
    Updates the element's text and re-pads the dots before it so the field keeps its width.

    length is the combined width of the dots run and the value; layout.field_len computes it
    from the column widths generate_svg.py laid the placeholders out with.

    The span is always ' ' + dots + ' '. The old code emitted ''/' '/'. ' once just_len fell
    to 2 or less -- two characters narrower than every other case -- so a column silently
    shrank by two as soon as a value grew that large, dragging the '|' separators out of
    line. Overflow raises rather than quietly misaligning.
    """
    if isinstance(new_text, int):
        new_text = f"{'{:,}'.format(new_text)}"
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    if not length:
        return
    just_len = length - len(new_text)
    if just_len < 1:
        raise Exception(f'justify_format(): {element_id}={new_text!r} overflows its column by {1 - just_len}')
    find_and_replace(root, f"{element_id}_dots", ' ' + ('.' * just_len) + ' ')


def find_and_replace(root, element_id, new_text):
    """
    Finds the element in the SVG file and replaces its text with a new value
    """
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def user_getter(username):
    """
    Returns the account ID and creation time of the user
    """
    query_count('user_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            id
            createdAt
        }
    }'''
    variables = {'login': username}
    request = simple_request(user_getter.__name__, query, variables)
    return {'id': request.json()['data']['user']['id']}, request.json()['data']['user']['createdAt']

def follower_getter(username):
    """
    Returns the number of followers of the user
    """
    query_count('follower_getter')
    query = '''
    query($login: String!){
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }'''
    request = simple_request(follower_getter.__name__, query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])


def query_count(funct_id):
    """
    Counts how many times the GitHub GraphQL API is called
    """
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def perf_counter(funct, *args):
    """
    Calculates the time it takes for a function to run
    Returns the function result and the time differential
    """
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


def formatter(query_type, difference, funct_return=False, whitespace=0):
    """
    Prints a formatted time differential
    Returns formatted result if whitespace is specified, otherwise returns raw result
    """
    global FORMATTER_LINES
    FORMATTER_LINES += 1
    print('{:<23}'.format('   ' + query_type + ':'), sep='', end='')
    print('{:>12}'.format('%.4f' % difference + ' s ')) if difference > 1 else print('{:>12}'.format('%.4f' % (difference * 1000) + ' ms'))
    if whitespace:
        return f"{'{:,}'.format(funct_return): <{whitespace}}"
    return funct_return


if __name__ == '__main__':
    """
    Haider Akbar (muhammadhaider02), adapted from Andrew Grant (Andrew6rant), 2022-2025
    """
    print('Calculation times:')
    # define global variable for owner ID and calculate user's creation date
    user_data, user_time = perf_counter(user_getter, USER_NAME)
    OWNER_ID, acc_date = user_data
    formatter('account data', user_time)
    ledger_guard()
    ledger_records, ledger_years, _ = ledger_load()
    cache_seed(ledger_records, 7)
    total_loc, loc_time = perf_counter(loc_query, ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'], 7)
    formatter('LOC (cached)', loc_time) if total_loc[-1] else formatter('LOC (no cache)', loc_time)
    (contributions_data, live_years), contributions_time = perf_counter(graph_commits, acc_date, ledger_years)
    formatter('contributions', contributions_time)
    # Persist immediately after the walk: the ledger is the only durable copy of the per-repo
    # figures and the per-year floors, and everything after this point can still fail.
    (ledger, ledger_changed), ledger_time = perf_counter(ledger_sync, cache_live_rows(7), live_years)
    formatter('ledger (%d repos%s)' % (len(ledger), ', written' if ledger_changed else ''), ledger_time)
    star_data, star_time = perf_counter(graph_repos_stars, 'stars', ['OWNER'])
    repo_data, repo_time = perf_counter(graph_repos_stars, 'repos', ['OWNER'])
    contrib_data, contrib_time = perf_counter(graph_repos_stars, 'repos', ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])
    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)

    for index in range(len(total_loc)-1): total_loc[index] = '{:,}'.format(total_loc[index]) # format added, deleted, and total LOC

    svg_overwrite('dark_mode.svg', contributions_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1])
    svg_overwrite('light_mode.svg', contributions_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1])

    # move cursor to override 'Calculation times:' with 'Total function time:' and the total function time, then move cursor back
    # Derived from the number of lines formatter() actually printed; the count used to be a
    # hardcoded run of eight escapes that no longer matched what was on screen.
    total_time = (user_time + loc_time + contributions_time + ledger_time
                  + star_time + repo_time + contrib_time + follower_time)
    print('\033[F' * (FORMATTER_LINES + 1),
        '{:<21}'.format('Total function time:'), '{:>11}'.format('%.4f' % total_time),
        ' s ', '\033[E' * (FORMATTER_LINES + 1), sep='')

    print('Total GitHub GraphQL API calls:', '{:>3}'.format(sum(QUERY_COUNT.values())))
    for funct_name, count in QUERY_COUNT.items(): print('{:<28}'.format('   ' + funct_name + ':'), '{:>6}'.format(count))