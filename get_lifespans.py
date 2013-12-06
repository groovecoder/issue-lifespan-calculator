#!/usr/bin/env python
from datetime import datetime, timedelta
import os
import time
from os.path import dirname
import hashlib
import urllib
import requests
import json

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


def add_repo_lifespans(lifespans, repo):
    print "Fetching lifespans for %s" % repo
    repo_url = '%s/repos/%s' % (GITHUB_API_HOST, repo)

    repoissues = api_get('%s/issues?per_page=100' % repo_url, None,
                         'repoissues', GITHUB_REPOS_CACHE_AGE)
    if type(repoissues) == dict:
        return
    repo_lifespans = []
    for repoissue in repoissues:
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
    avg_lifespan = total_lifespan / len(repoissues)

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

    # If data was missing or stale from cache, finally perform GET
    if not data:
        print "GET %s" % url
        data = requests.get(url).json()
        json.dump(data, open(cache_path, 'w'))

    return data


def file_age(fn):
    """Get the age of a file in seconds"""
    return time.time() - os.stat(fn).st_mtime


if __name__ == '__main__':
    main()
