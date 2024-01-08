# Use an official Python runtime as the base image
FROM python:3.8-slim

# Environment variables for Flask
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000

ENV SERVICE_ACCOUNT_FILE=""
ENV GOOGLE_ADMIN_SUBJECT=""
ENV GROUPSIO_USER=""
ENV GROUPSIO_PASSWORD=""
ENV GITHUB_TOKEN=""
ENV JIRA_TOKEN=""
ENV JIRA_URL=""
ENV ORG=""
ENV TEAM_SLUG=""

# Set the working directory in the container to /app
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Run gunicorn
CMD ["gunicorn", "-w", "4", "-b", ":5000", "app:app"]