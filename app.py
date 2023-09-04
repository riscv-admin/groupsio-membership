#!/usr/bin/env python3

# Copyright 2023 RISC-V International
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#   Rafael Sene rafael@riscv.org - Intial commit.

from flask import Flask, render_template, request, redirect, url_for
from typing import Dict, List
import logging
import sys
import requests
import re
import os

app = Flask(__name__)
app.config['ENV'] = 'production'
app.config['DEBUG'] = False

def get_authenticated_session(user: str, password: str):
    """
    Authenticate with the Groups.io API and return an authenticated session.

    Args:
        user (str): The username for authentication.
        password (str): The password for authentication.

    Returns:
        requests.Session: An authenticated session.
    """
    session = requests.Session()
    login = session.post(
        'https://groups.io/api/v1/login',
        data={'email': user, 'password': password}
    ).json()

    if 'user' not in login:
        print('\nAuthentication failed.\n')
        sys.exit()

    csrf = login['user']['csrf_token']
    return session, csrf


def find_pending_accounts(session, group: str):
    """
    Finds all pending accounts in a given group on groups.io and returns them in a list.

    Parameters:
    - session: The authenticated session for making API calls to groups.io.
    - group: A dictionary containing information about the group, including its name.

    Returns:
    - A list of email addresses for accounts that are pending in the specified group.
    """
    next_page_token_pending_members = 0
    pending_members = True
    pending = []

    while pending_members:
        # Fixed the indentation
        pending_member_data = session.post(
            f"https://groups.io/api/v1/getmembers?group_name={group['group_name']}&type=pending&page_token={next_page_token_pending_members}"
        ).json()

        next_page_token_pending_members = pending_member_data.get('next_page_token', 0)

        if next_page_token_pending_members == 0:
            pending_members = False

        for member in pending_member_data['data']:
            pending.append(member["email"])

    return pending


def find_monitored_groups(session, search_email: str):
    """
    Search the Groups.io for groups monitored by the admin and check membership of the user.

    Args:
        session (requests.Session): The authenticated session.
        search_email (str): The email to search for in the groups.

    Returns:
        Dict: Information about monitored groups.
        List: Groups where the email was found.
    """
    next_page_token_groups = 0
    more_groups = True
    monitored_groups = {}
    found_accounts = []

    while more_groups:
        groups_page = session.post(
            f'https://groups.io/api/v1/getsubs?limit=100&sort_field=group&page_token={next_page_token_groups}',
        ).json()

        if groups_page['object'] == 'error':
            print(f"Something went wrong: {groups_page['type']}")
            sys.exit()

        if 'data' in groups_page:
            for group in groups_page['data']:
                if group['group_name'] != 'beta' and '+' not in group['group_name']:
                    process_group(session, group, monitored_groups, search_email, found_accounts)

        next_page_token_groups = groups_page.get('next_page_token', 0)

        if next_page_token_groups == 0:
            more_groups = False

    return monitored_groups, found_accounts


def process_group(session, group, monitored_groups: Dict, search_email: str, found_accounts: List):
    """
    Process a single group to find out whether the user is a member and add the information to existing dictionaries/lists.

    Args:
        session (requests.Session): The authenticated session.
        group (Dict): The current group being processed.
        monitored_groups (Dict): A dictionary of monitored groups.
        search_email (str): The email to search for in the group.
        found_accounts (List): A list of groups where the email was found.
    """
    group_data = session.post(
        f"https://groups.io/api/v1/getgroup?group_name={group['group_name']}",
    ).json()

    monitored_groups[group['group_name']] = {
        'title': group_data['title'][:-11],
        'domain': group_data['org_domain'],
        'alias': group_data['alias'],
        'subs_count': group_data['subs_count'],
        'email_address': group_data['email_address']
    }

    pending_members = find_pending_accounts(session, group)

    search_group = session.post(
        f"https://groups.io/api/v1/searchmembers?group_name={group['group_name']}&q={search_email.replace('+', '%2B')}",
    ).json()

    if search_group['total_count'] and search_group['data'][0]['email'] not in pending_members:
        found_accounts.append(group['group_name'])
        print(f"  - {search_email} is a RISC-V Member and part of {monitored_groups[group['group_name']]['email_address']}")
    else:
        print(f"  - {search_email} is not a member of RISC-V")

@app.route('/', methods=['GET', 'POST'])
def index():
    logging.basicConfig(filename='error.log', level=logging.ERROR)
    message = ""
    status = ""
    if request.method == 'POST':
        search_email = request.form['email']
        if not re.match(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", search_email):
            message = 'This does not appear to be a valid email'
            status = "failure"
        else:
            user = os.environ.get("EMAIL_USER")
            password = os.environ.get("EMAIL_PASSWORD")

            session, _ = get_authenticated_session(user, password)
            _, found_accounts = find_monitored_groups(session, search_email)
            if found_accounts:
                message = f"{search_email} is a RISC-V Member"
                status = "success"
            else:
                message = f"{search_email} is not a member of RISC-V"
                status = "failure"

    return render_template("index.html", message=message, status=status)


if __name__ == '__main__':
    app.run(debug=True)