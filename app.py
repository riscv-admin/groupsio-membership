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
#   Rafael Sene rafael@riscv.org - Initial commit.

# Standard library imports
import re
import os
import sys
import time

# Related third-party imports
from flask import Flask, request, render_template
from jira import JIRA
from jira.exceptions import JIRAError
import requests
from typing import Dict, List
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Configuration and Credentials
SERVICE_ACCOUNT_FILE = os.environ.get("SERVICE_ACCOUNT_FILE")
GOOGLE_ADMIN_SUBJECT = os.environ.get("GOOGLE_ADMIN_SUBJECT")
GROUPSIO_USER = os.environ.get("GROUPSIO_USER")
GROUPSIO_PASSWORD = os.environ.get("GROUPSIO_PASSWORD")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
JIRA_TOKEN = os.environ.get("JIRA_TOKEN")
JIRA_URL = os.environ.get("JIRA_URL")
ORG = os.environ.get("ORG")
TEAM_SLUG = os.environ.get("TEAM_SLUG")

app = Flask(__name__)

# Google Groups
def authenticate_service():
    """Authenticate using the service account."""
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/admin.directory.group.readonly"],
    )

    # Impersonate a user with domain-wide delegation
    credentials = credentials.with_subject(GOOGLE_ADMIN_SUBJECT)

    service = build("admin", "directory_v1", credentials=credentials)
    return service


def is_member_of_google_group(service, member_email, group_email):
    """Check if the user is a member of the group."""
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            request = service.members().list(groupKey=group_email)

            while request is not None:
                response = request.execute()
                for member in response.get("members", []):
                    if member["email"].lower() == member_email.lower():
                        return True
                request = service.members().list_next(
                    previous_request=request, previous_response=response
                )
            return False  # Return False if the member is not found after all pages are checked.
        except Exception as e:
            print(f"Attempt {attempt + 1} failed with error: {e}")
            if (
                attempt < max_attempts - 1
            ):  # Wait a bit before retrying unless it's the last attempt.
                time.sleep(2**attempt)  # Exponential backoff
            else:
                print("Max attempts reached. Exiting.")
    return False  # Return False if all attempts fail.


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
        link_header = response.headers.get("Link", None)
        team_members_url = None

        if link_header:
            links = link_header.split(",")
            for link in links:
                # Extract the URL and the "rel" type
                url, rel = link.split(";")
                url = url.strip()[
                    1:-1
                ]  # Remove leading and trailing angle brackets and whitespaces
                rel = rel.strip()

                if 'rel="next"' in rel:
                    team_members_url = url
                    break

    return all_members


def check_if_user_is_in_team(gh_login, gh_token):
    is_member = False
    team_members = get_all_team_members(GITHUB_TOKEN, ORG, TEAM_SLUG)

    for member in team_members:
        if member["login"] == gh_login:
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
    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
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
        "https://groups.io/api/v1/login", data={"email": user, "password": password}
    ).json()

    if "user" not in login:
        print("\nAuthentication failed.\n")
        sys.exit()

    csrf = login["user"]["csrf_token"]
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

        next_page_token_pending_members = pending_member_data.get("next_page_token", 0)

        if next_page_token_pending_members == 0:
            pending_members = False

        for member in pending_member_data["data"]:
            pending.append(member["email"])

    return pending


def find_member(session, search_email):
    account_found = False
    results = {}
    search_group = session.post(
        f"https://groups.io/api/v1/searchmembers?group_name=risc-v&q={search_email.replace('+', '%2B')}",
    ).json()

    if search_group["data"]:
        for member in search_group["data"]:
            if search_email == member["email"]:
                account_found = True
                if "extra_member_data" in member:
                    #print (member["extra_member_data"])
                    for item in member["extra_member_data"]:
                        col_id = item["col_id"]
                        if col_id in [
                            2,
                            3,
                            4,
                            5,
                            8,
                        ]:  # Check if col_id is one of the ones we're interested in
                            if item["col_type"] == "text" and item.get(
                                "text"
                            ):  # Check if 'text' is not None or empty
                                results[f"col_id_{col_id}_text"] = item["text"]
                            elif item["col_type"] == "checkbox":
                                results[f"col_id_{col_id}_checked"] = item["checked"]
                print(f"  - {search_email} is a RISC-V Member and part of RISC-V")
    else:
        print(f"  - {search_email} is not a member of RISC-V")
    return account_found, results


@app.route("/", methods=["GET", "POST"])
def groupsio_search():
    """
    Search for a given email in the Groups.io system and retrieve related status information.
    """
    service = authenticate_service()
    try:
        email = request.form.get("email")
        # Check if email is not null and validate email
        if not email or not is_valid_email(email):
            return render_template(
                "index.html",
                status="warning",
                message=f'<span style="font-weight: bold; font-size: medium;">Enter a valid email address to proceed!</span>'
            )

        user = GROUPSIO_USER
        password = GROUPSIO_PASSWORD

        session, _ = get_authenticated_session(user, password)
        found_account, extra = find_member(session, email)

        if found_account:
            # Initialize the data_status dictionary with default values
            data_status = {
                "GitHub_ID": "❌",
                "GitHub_ID_Member": "❌",
                "LFX_Email": "❌",
                "Google_Drive_Email": "❌",
                "Google_Drive_Member": "❌",
                "Google_Drive_Committee_Chairs": "❌",
                "Google_Drive_Tech_Chairs": "❌",
                "Google_Drive_TSC": "❌",
                "Checkbox_Status": "❌",
                "Jira": "❌",
                "ChairViceChair": "❌",
            }

            if "col_id_2_text" in extra:
                data_status["GitHub_ID"] = "✅"
                data_status["GitHub_ID_Member"] = (
                    "✅"
                    if check_if_user_is_in_team(
                        extra["col_id_2_text"],
                        GITHUB_TOKEN,
                    )
                    else "❌"
                )
            if "col_id_3_text" in extra:
                data_status["LFX_Email"] = "✅"
            if "col_id_4_text" in extra:
                data_status["Google_Drive_Email"] = "✅"
                data_status["Google_Drive_Member"] = (
                    "✅"
                    if is_member_of_google_group(service, email, "members@riscv.org")
                    else "❌"
                )
                data_status["Google_Drive_Committee_Chairs"] = (
                    "✅"
                    if is_member_of_google_group(
                        service, email, "committee-chairs@riscv.org"
                    )
                    else "❌"
                )
                data_status["Google_Drive_Tech_Chairs"] = (
                    "✅"
                    if is_member_of_google_group(
                        service, email, "tech-chairs-vicechairs@riscv.org"
                    )
                    else "❌"
                )
                data_status["Google_Drive_TSC"] = (
                    "✅"
                    if is_member_of_google_group(service, email, "tsc@riscv.org")
                    else "❌"
                )
            if "col_id_5_checked" in extra:
                data_status["Checkbox_Status"] = (
                    "✅" if extra["col_id_5_checked"] else "❌"
                )
            if "col_id_8_checked" in extra:
                data_status["ChairViceChair"] = (
                    "✅" if extra["col_id_8_checked"] else "❌"
                )

            try:
                # Initialize Jira connection
                jira = JIRA(
                    "https://jira.riscv.org",
                    token_auth=JIRA_TOKEN,
                )

                # Check if user is in Jira
                if check_if_user_is_in_jira(email, jira):
                    data_status["Jira"] = "✅"
                else:
                    data_status["Jira"] = "❌"

            except JIRAError as e:
                print(f"Encountered an error with JIRA: {e}")
                data_status["Jira"] = "Error"
            message = (
                f'<span style="font-weight: bold; font-size: larger;">{email}</span> \n\n'
                f"RISC-V Groups.io Account   ✅\n\n"
                f'<span style="font-weight: bold; font-size: larger;">Accounts Credentials</span> \n\n'
                f"GitHub ID is set in Groups.io  {data_status['GitHub_ID']}\n"
                f"LFX Email is set in Groups.io  {data_status['LFX_Email']}\n"
                f"Google Drive Email is set in Groups.io {data_status['Google_Drive_Email']}\n\n"
                f'<span style="font-weight: bold; font-size: larger;">Tools Access</span> \n\n'
                f"RISC-V GitHub Team Access {data_status['GitHub_ID_Member']}\n"
                f"Google Drive Member Access {data_status['Google_Drive_Member']}\n"
                f"Google Drive Committee Chairs Access {data_status['Google_Drive_Committee_Chairs']}\n"
                f"Google Drive Tech Chairs Access {data_status['Google_Drive_Tech_Chairs']}\n"
                f"Google Drive TSC Access {data_status['Google_Drive_TSC']}\n"
                f"Jira Access {data_status['Jira']}\n\n"
                f'If you got ❌ for GitHub ID, LFX Email \n or Google Drive Email, '
                f'<a href="https://lists.riscv.org/g/main/editprofile">update your Groups.io profile</a> \n\n'
                f'If you got ❌ for any Tool Access, reach out to <span style="font-weight: bold; font-size: medium;">help@riscv.org</span>'
            )
            status = "success"
        else:
            message = (
                f'<span style="font-weight: bold; font-size: medium;">{email} \n\nNOT found in RISC-V Groups.io!\n\n</span>'
                f"Please, reach out to <a href='mailto:help@riscv.org'>help@riscv.org</a>!"
            )
            status = "failure"

        return render_template("index.html", message=message, status=status)

    except Exception as e:
        error_message = (
            f"An error occurred: {str(e)}\n\n"
            f"If you need assistance, please contact <a href='mailto:help@riscv.org'>help@riscv.org</a>!"
        )
        return render_template("index.html", status="failure", message=error_message)


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html", status="failure", message="Page not found")


if __name__ == "__main__":
    app.run(debug=True)
