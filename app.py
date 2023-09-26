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

# Standard library imports
import os
import re
import sys

# Related third-party imports
from flask import Flask, request, render_template
from jira import JIRA
from jira.exceptions import JIRAError
import requests
from typing import Dict, List


app = Flask(__name__)

# GitHub
def get_all_team_members(gh_token, org, team_slug):
    team_members_url = f"https://api.github.com/orgs/{org}/teams/{team_slug}/members"
    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    all_members = []
    
    while team_members_url:
        response = requests.get(team_members_url, headers=headers)
        
        if response.status_code != 200:
            print(f"Failed to fetch team members: {response.content}")
            return []
        
        all_members.extend(response.json())
        
        # Check for Link header for pagination
        link_header = response.headers.get('Link', None)
        team_members_url = None
        
        if link_header:
            links = link_header.split(',')
            for link in links:
                # Extract the URL and the "rel" type
                url, rel = link.split(';')
                url = url.strip()[1:-1]  # Remove leading and trailing angle brackets and whitespaces
                rel = rel.strip()

                if 'rel="next"' in rel:
                    team_members_url = url
                    break
    
    return all_members


def check_if_user_is_in_team(gh_login, gh_token):
    org = "riscv-admin"
    team_slug = "riscv-members"
    is_member = False  # Rename variable to avoid confusion
    team_members = get_all_team_members(gh_token, org, team_slug)
    
    for member in team_members:
        if member['login'] == gh_login:
            print(f"{gh_login} is a member of the RISC-V team.")
            is_member = True
            break
    
    if not is_member:
        print(f"{gh_login} is NOT a member of the RISC-V team.")
        
    return is_member


# Jira
def check_if_user_is_in_jira(email, jira):
    users = jira.search_users(email)
    for user in users:
        if user.emailAddress == email:
            return True
    return False


def is_valid_email(email):
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(email_regex, email))


# Groups.io
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
                    account, extra = process_group(session, group, monitored_groups, search_email, found_accounts)

        next_page_token_groups = groups_page.get('next_page_token', 0)

        if next_page_token_groups == 0:
            more_groups = False

    return monitored_groups, account, extra


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
    extra_member_data = ""

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

    data_status = {
        "GitHub_ID": "is not set",
        "LFX_Email": "is not set",
        "Google_Drive_Email": "is not set",
        "Checkbox_Status": "is not set"
    }

    pending_members = find_pending_accounts(session, group)

    search_group = session.post(
        f"https://groups.io/api/v1/searchmembers?group_name={group['group_name']}&q={search_email.replace('+', '%2B')}",
    ).json()

    if search_group['total_count'] and search_group['data'][0]['email'] not in pending_members:
        found_accounts.append(group['group_name'])
        extra_member_data = search_group['data'][0]['extra_member_data']
        for item in extra_member_data:
            if item['col_id'] == 2 and 'text' in item and item['text']:
                data_status["GitHub_ID"] = "is set"
            elif item['col_id'] == 3 and 'text' in item and item['text']:
                data_status["LFX_Email"] = "is set"
            elif item['col_id'] == 4 and 'text' in item and item['text']:
                data_status["Google_Drive_Email"] = "is set"
            elif item['col_id'] == 5 and 'checked' in item:
                data_status["Checkbox_Status"] = "is set" if item['checked'] else "is not set"
        print(f"  - {search_email} is a RISC-V Member and part of {monitored_groups[group['group_name']]['email_address']}")
    else:
        print(f"  - {search_email} is not a member of RISC-V")
    return found_accounts, extra_member_data

@app.route('/', methods=['GET', 'POST'])
def index():
    placeholder_text = "Enter email for Groups.io"
    status = ""
    message = ""
    return render_template('index.html', placeholder_text=placeholder_text, status=status, message=message)


@app.route('/groupsio', methods=['POST'])
def groupsio_search():
    try:
        email = request.form.get('email')
        # Validate email
        if not is_valid_email(email):
            return render_template('index.html', status="failure", message=f"{email} is NOT a valid email address")

        if request.method == 'POST':
            search_email = request.form['email']
            user = os.environ.get("GROUPSIO_EMAIL_USER")
            password = os.environ.get("GROUPSIO_EMAIL_PASSWORD")

            session, _ = get_authenticated_session(user, password)
            _, found_accounts, extra = find_monitored_groups(session, search_email)
            if found_accounts:
                data_status = extra[0]
                # Populate the dictionary based on the extra_member_data list
                for item in extra:
                    if item['col_id'] == 2 and 'text' in item and item['text']:
                        data_status['GitHub_ID'] = "is set"
                    elif item['col_id'] == 3 and 'text' in item and item['text']:
                        data_status['LFX_Email'] = "is set"
                    elif item['col_id'] == 4 and 'text' in item and item['text']:
                        data_status['Google_Drive_Email'] = "is set"
                    elif item['col_id'] == 5 and 'checked' in item:
                        data_status['Checkbox_Status'] = "is set" if item['checked'] else "is not set"

                # Construct the message string using the populated data_status dictionary
                message = f"{search_email} is a RISC-V Groups.io Member!\n\n"\
                            f"GitHub ID {data_status['GitHub_ID']}\n"\
                            f"LFX Email {data_status['LFX_Email']}\n"\
                            f"Google Drive Email {data_status['Google_Drive_Email']}\n"\
                            f"Vote by Code Checkbox {data_status['Checkbox_Status']}\n\n"\
                            f'Profile Update: <a href="https://lists.riscv.org/g/main/editprofile">https://lists.riscv.org/g/main/editprofile</a>'
                status = "success"
            else:
                message = f"{search_email} is NOT a member of RISC-V Groups.io. \n\n"\
                            f"If need be, ask for help at <a href='mailto:help@riscv.org'>help@riscv.org</a>!"
                status = "failure"

            return render_template("index.html", message=message, status=status)
    except Exception as e:
        error_message = f"An error occurred while searching for {email}: {str(e)}\n\n"\
                        f"If need be, ask for help at <a href='mailto:help@riscv.org'>help@riscv.org</a>!"
        return render_template('index.html', status="failure", message=error_message)

@app.route('/github', methods=['POST'])
def github_search():
    github_username = request.form.get('github')
    gh_token = os.environ.get("GITHUB_TOKEN")

    try:
        if check_if_user_is_in_team(github_username, gh_token):
            return render_template('index.html', status="success", message=f"{github_username} is a member of the RISC-V GitHub Organization")
        else:
            message = f"{github_username} is NOT a member of the RISC-V GitHub Organization. \n\n"\
                        f"If need be, ask for help at <a href='mailto:help@riscv.org'>help@riscv.org</a>!"
            return render_template('index.html', status="failure", message=message)

    except Exception as e:  # This will capture any general exception
        error_message = f"An error occurred while searching for {github_username}: {str(e)}\n\n"\
                        f"If need be, ask for help at <a href='mailto:help@riscv.org'>help@riscv.org</a>!"
        return render_template('index.html', status="failure", message=error_message)


@app.route('/jira', methods=['POST'])
def jira_search():
    jira_email = request.form.get('jira')

    # Validate email
    if not is_valid_email(jira_email):
        return render_template('index.html', status="failure", message=f"{jira_email} is NOT a valid email address")

    try:
        # Create a JIRA connection
        jira = JIRA("https://jira.riscv.org", token_auth=os.environ.get("JIRA_TOKEN"))
        is_user = check_if_user_is_in_jira(jira_email, jira)

        if is_user:
            return render_template('index.html', status="success", message=f"{jira_email} is a RISC-V Jira user")
        else:
            message = f"{jira_email} is NOT a RISC-V Jira user. \n\n"\
                        f"If need be, ask for help at <a href='mailto:help@riscv.org'>help@riscv.org</a>!"
            return render_template('index.html', status="failure", message=message)
    
    except JIRAError:
        message = f"Failed to connect to JIRA or authenticate. \n\n"\
                  f"Notify this issue via <a href='mailto:help@riscv.org'>help@riscv.org</a>!"
        return render_template('index.html', status="failure", message=message)


if __name__ == '__main__':
    app.run(debug=True)
