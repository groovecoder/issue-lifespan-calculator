#!/usr/bin/env python
from datetime import datetime, timedelta
import os
import time
from os.path import dirname
import hashlib
import urllib
import requests
import json
import re

from repos import repos

# Quick & dirty env-based config
# See also: https://developer.github.com/v3/#rate-limiting
GITHUB_CLIENT_ID = os.getenv('GITHUB_CLIENT_ID', None)
GITHUB_CLIENT_SECRET = os.getenv('GITHUB_CLIENT_SECRET', None)
GITHUB_EMAIL_CACHE_AGE = int(os.getenv('GITHUB_EMAIL_CACHE_AGE',
                                       60 * 60 * 24 * 7))
GITHUB_REPOS_CACHE_AGE = int(os.getenv('GITHUB_REPOS_CACHE_AGE',
                                       60 * 60))

CACHE_PATH_TMPL = 'cache/%s/%s'

GITHUB_API_HOST = 'https://api.github.com'
base_url = '%s/repos' % GITHUB_API_HOST
commit_levels = [1000,500,250,100, 50, 25, 10, 1, 0]
avg_lifespans = {}
contributors_by_level = {}


def get_repo_issues(starting_url):
    repo_issues = []
    page_num = 1
    issues, next_page = api_get(starting_url,
                                None,
                                'repoissues_page_%s' % page_num,
                                GITHUB_REPOS_CACHE_AGE)
    repo_issues += issues
    while next_page:
        issues, next_page = api_get(next_page,
                                    None,
                                    'repoissues_page_%s' % page_num,
                                    GITHUB_REPOS_CACHE_AGE)
        repo_issues += issues
    return repo_issues


def add_repo_lifespans(lifespans, repo):
    print "Fetching lifespans for %s" % repo
    repo_url = '%s/repos/%s' % (GITHUB_API_HOST, repo)

    open_url = '%s/issues?per_page=100' % repo_url
    open_issues = get_repo_issues(open_url)
    closed_url = '%s/issues?per_page=100&state=closed' % repo_url
    closed_issues = get_repo_issues(closed_url)

    repo_issues = open_issues + closed_issues
    if type(repo_issues) == dict:
        return
    repo_lifespans = []
    for repoissue in repo_issues:
        if repoissue['closed_at'] is None:
            closed_at = datetime.utcnow()
        else:
            closed_at = datetime.strptime(repoissue['closed_at'],
                                          '%Y-%m-%dT%H:%M:%SZ')
        created_at = datetime.strptime(repoissue['created_at'],
                                          '%Y-%m-%dT%H:%M:%SZ')
        issue_lifespan = closed_at - created_at
        repo_lifespans.append(issue_lifespan)
    total_lifespan = timedelta()
    for lifespan in repo_lifespans:
        total_lifespan += lifespan
    avg_lifespan = total_lifespan / len(repo_issues)

    print "repo: %s avg issue lifespan: %s" % (repo, avg_lifespan)


def main():
    # Figure out the number of contributions per contributor:
    for repo in repos:
        # "repo" is an org, get all source repos under it
        if repo[-1] == '/':
            org_repos = api_get('%s/orgs/%srepos' % (GITHUB_API_HOST, repo),
                                {'type': 'sources'}, 'org_repos',
                                GITHUB_REPOS_CACHE_AGE)
            for org_repo in org_repos:
                add_repo_lifespans(avg_lifespans, org_repo['full_name'])

        else:
            add_repo_lifespans(avg_lifespans, repo)


def api_url(url, params=None):
    """Append the GitHub client details, if available"""
    if not params:
        params = {}
    if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:
        params.update(dict(
            client_id = GITHUB_CLIENT_ID,
            client_secret = GITHUB_CLIENT_SECRET
        ))
    if params:
        url = '%s?%s' % (url, urllib.urlencode(params))
    return url


def api_get(path, params=None, cache_name=False, cache_timeout=86400):
    """Cached HTTP GET to GitHub repos API"""
    url = api_url(path, params)

    # If no cache name, then cache is disabled.
    if not cache_name:
        return requests.get(url).json()

    # Build a cache path based on MD5 of URL
    path_hash = hashlib.md5(url).hexdigest()
    cache_path = CACHE_PATH_TMPL % (cache_name, path_hash)

    # Create the cache path, if necessary
    cache_dir = dirname(cache_path)
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    # Attempt to load up data from cache
    data = None
    if os.path.exists(cache_path) and file_age(cache_path) < cache_timeout:
        try:
            data = json.load(open(cache_path, 'r'))
        except ValueError:
            pass

    next_page = None
    # If data was missing or stale from cache, finally perform GET
    if not data:
        print "GET %s" % url
        resp = requests.get(url)
        link = resp.headers['Link']
        if link:
            next_page_match = re.match('\<(.*)\>; rel="next"', link)
            if next_page_match:
                next_page = next_page_match.group(1)
        data = resp.json()
        json.dump(data, open(cache_path, 'w'))

    return data, next_page


def file_age(fn):
    """Get the age of a file in seconds"""
    return time.time() - os.stat(fn).st_mtime


if __name__ == '__main__':
    main()
