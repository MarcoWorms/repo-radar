import os
import time
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from github import Github
import openai
from dotenv import load_dotenv
import requests


load_dotenv()  # This line loads the environment variables from the .env file

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GITHUB_ACCESS_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Set up GitHub API
github_api = Github(GITHUB_ACCESS_TOKEN)

# Set up OpenAI API
openai.api_key = OPENAI_API_KEY

# List of GitHub orgs to monitor
# GITHUB_ORGS = ['ethereum', 'yearn', 'makerdao', 'curvefi', 'uniswap', 'sushiswap', 'compound-finance', 'convex-eth', 'alchemix-finance', 'bitcoin']
GITHUB_ORGS = ['yearn', 'makerdao']

def summarize_diff(diff_text):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a diff sumarizer assistant. I will pass a PR diff and you will reply with a layman-readable summary for what relevant changes happened in the code. Reply with direct summaries."},
            {"role": "user", "content": f"Summarize the following PR code diff: {diff_text}"}
        ]
    )
    return response.choices[0].message['content']

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Hi! I am a GitHub PR monitoring bot. Use the /monitor_prs command to start monitoring PRs!')

class PRMonitor:
    def __init__(self):
        self.sent_prs = {}

    def monitor_prs(self, context: CallbackContext):
        chat_id = context.job.context

        if chat_id not in self.sent_prs:
            self.sent_prs[chat_id] = set()

        for org_name in GITHUB_ORGS:
            org = github_api.get_organization(org_name)

            for repo in org.get_repos():
                for pr in repo.get_pulls(state='open'):
                    if pr.id in self.sent_prs[chat_id]:
                        continue

                    pr_title = pr.title
                    pr_description = pr.body

                    # Download the diff file using the patch_url
                    diff_response = requests.get(pr.patch_url)
                    diff_text = diff_response.text

                    # Get commit messages
                    commit_messages = "\n".join([commit.commit.message for commit in pr.get_commits()])

                    # Split the diff_text into chunks of 10000 characters or less
                    max_chunk_size = 10000
                    diff_chunks = [diff_text[i:i + max_chunk_size] for i in range(0, len(diff_text), max_chunk_size)]

                    # Summarize each chunk and concatenate the summaries
                    summaries = []
                    for chunk in diff_chunks:
                        # Truncate the diff chunk to ensure it doesn't exceed the token limit
                        title_desc_and_commits = f"Title: {pr_title}\nDescription: {pr_description}\nCommit messages: {commit_messages}\n"
                        tokens_reserved_for_title_desc_and_commits = len(openai.api.encoder.encode(title_desc_and_commits))
                        max_diff_tokens = 4097 - tokens_reserved_for_title_desc_and_commits
                        diff_chunk_truncated = openai.api.encoder.decode(openai.api.encoder.encode(chunk)[:max_diff_tokens])

                        response = openai.ChatCompletion.create(
                            model="gpt-3.5-turbo",
                            messages=[
                                {"role": "system", "content": "You are a helpful assistant."},
                                {"role": "user", "content": f"Summarize the following PR title, description, commit messages, and code diff chunk:\n\n{title_desc_and_commits}Diff: {diff_chunk_truncated}"}
                            ]
                        )
                        summaries.append(response.choices[0].message['content'])

                    # Concatenate the summaries
                    final_summary = " ".join(summaries)

                    context.bot.send_message(chat_id, f"{org_name}: {final_summary}\n\n📡 {pr.html_url}")
                    self.sent_prs[chat_id].add(pr.id)

def monitor_prs(update: Update, context: CallbackContext) -> None:
    interval = 60  # Time in seconds between PR checks
    chat_id = update.effective_chat.id
    pr_monitor = PRMonitor()

    if 'monitor_prs_job' in context.chat_data:
        update.message.reply_text('PR monitoring is already running.')
    else:
        context.chat_data['monitor_prs_job'] = context.job_queue.run_repeating(pr_monitor.monitor_prs, interval, context=chat_id)
        update.message.reply_text('Started monitoring PRs.')

def stop_monitor(update: Update, context: CallbackContext) -> None:
    if 'monitor_prs_job' not in context.chat_data:
        update.message.reply_text('No PR monitoring is currently running.')
    else:
        context.chat_data['monitor_prs_job'].schedule_removal()
        del context.chat_data['monitor_prs_job']
        update.message.reply_text('Stopped monitoring PRs.')

def main():
    updater = Updater(TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("monitor_prs", monitor_prs))
    dispatcher.add_handler(CommandHandler("stop_monitor", stop_monitor))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()