# made entirely with gpt4 ;)

import os
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from github import Github, GithubException
import openai
from dotenv import load_dotenv
import requests
import time
from functools import lru_cache
from datetime import datetime, timedelta

load_dotenv()
t_token = os.getenv("TELEGRAM_BOT_TOKEN")
gh_token = os.getenv("GITHUB_ACCESS_TOKEN")
oai_key = os.getenv("OPENAI_API_KEY")
github_api = Github(gh_token)
openai.api_key = oai_key
gh_orgs = ['yearn', 'makerdao', 'curvefi', 'Uniswap', 'sushiswap', 'compound-finance', 'aave', 'balancer-labs', 'alchemix-finance', 'redacted-cartel']

def start(u: Update, c: CallbackContext) -> None:
    u.message.reply_text('Hi! I am a GitHub PR monitoring bot. Use the /monitor_prs command to start monitoring PRs!')

class PRMonitor:
    def __init__(self):
        self.sp = {}
        self.org_cache = {}  # Cache for organization data
        self.last_updated = datetime.now() - timedelta(days=1)  # Initial value for last update check

    @lru_cache(maxsize=None)
    def get_org_repos(self, o_name, since):
        try:
            org = github_api.get_organization(o_name)
            repos = org.get_repos(since=since.isoformat())

            # Check rate limit remaining and reset time
            rate_limit_remaining = int(repos.raw_headers.get("x-ratelimit-remaining", "60"))
            rate_limit_reset = int(repos.raw_headers.get("x-ratelimit-reset", "0"))

            if rate_limit_remaining == 0:
                reset_time = datetime.fromtimestamp(rate_limit_reset)
                wait_time = (reset_time - datetime.now()).total_seconds()
                print(f"Rate limit exceeded. Waiting for {wait_time} seconds.")
                time.sleep(wait_time)

            return list(repos)  # Convert to list to make it cacheable

        except GithubException as e:
            print(f"Error fetching organization {o_name}: {e}")
            return []

    def m_prs(self, c: CallbackContext):
        cid = c.job.context
        if cid not in self.sp:
            self.sp[cid] = {'s_prs': set(), 'm_start': time.time()}
        m_start = self.sp[cid]['m_start']

        print("Checking PRs...")

        current_time = datetime.now()

        for o_name in gh_orgs:
            if o_name not in self.org_cache or current_time - self.last_updated > timedelta(minutes=30):
                self.org_cache[o_name] = self.get_org_repos(o_name, self.last_updated)

            for repo in self.org_cache[o_name]:
                try:
                    pr_list = repo.get_pulls(state='open', per_page=10)  # Fetch paginated results
                except GithubException as e:
                    print(f"Error fetching PRs for repo {repo.name}: {e}")
                    continue

                for pr in pr_list:
                    if pr.id in self.sp[cid]['s_prs'] or pr.created_at.timestamp() < m_start:
                        continue

                    print(f"Found new PR: {pr.html_url}")

                    pr_title = pr.title
                    pr_desc = pr.body
                    diff_resp = requests.get(pr.patch_url)
                    diff_txt = diff_resp.text
                    cm_msgs = "\n".join([cm.commit.message for cm in pr.get_commits()])
                    full_txt = f"Title: {pr_title}\nDescription: {pr_desc}\nCommit messages: {cm_msgs}\nDiff: {diff_txt}"
                    max_c = 10000
                    chunks = [full_txt[i:i + max_c] for i in range(0, len(full_txt), max_c)]

                    print("Summarizing PR...")

                    summaries = []
                    res = None

                    for chunk in chunks:
                        res = openai.ChatCompletion.create(
                            model="gpt-3.5-turbo",
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You are an AI assistant specialized in summarizing GitHub pull requests. Your task is to provide concise and informative summaries that help users understand the most important and relevant changes made in the code. Avoid mentioning less important details."
                                },
                                {
                                    "role": "user",
                                    "content": f"Summarize the following PR information, focusing on the most important changes:\n\n{chunk}"
                                }
                            ]

                        )
                        summaries.append(res.choices[0].message['content'])

                    if len(chunks) > 1:
                        res = openai.ChatCompletion.create(
                            model="gpt-3.5-turbo",
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You are an AI assistant that can generate a brief and coherent summary based on multiple summaries. Your task is to provide a single, easily understandable summary that highlights the most important information from the given summaries."
                                },
                                {
                                    "role": "user",
                                    "content": f"Summarize the following summaries:\n\n{' '.join(summaries)}"
                                }
                            ]
                        )
                    
                    f_summary = res.choices[0].message['content']

                    print(f"Sending summary: {f_summary}")

                    try:
                        c.bot.send_message(cid, f"*PR Summary:* {f_summary}\n\n*PR Link:* {pr.html_url}", parse_mode='Markdown')
                    except Exception as e:
                        print(f"Error sending message: {e}")
                        self.sp[cid]['s_prs'].add(pr.id)

            self.last_updated = current_time
            time.sleep(1)  # Sleep for a short duration to avoid rate-limiting

def monitor_prs(u: Update, c: CallbackContext) -> None:
    if u.effective_chat.id != -1001798829382:
        u.message.reply_text("Sorry, this bot is limited to a specific group.")
        return

    interval = 60
    cid = u.effective_chat.id
    pr_mon = PRMonitor()

    if 'monitor_prs_job' in c.chat_data:
        u.message.reply_text('PR monitoring is already running.')
    else:
        c.chat_data['monitor_prs_job'] = c.job_queue.run_repeating(pr_mon.m_prs, interval, context=cid)
        u.message.reply_text('Started monitoring PRs.')

def stop_monitor(u: Update, c: CallbackContext) -> None:
    if 'monitor_prs_job' not in c.chat_data:
        u.message.reply_text('No PR monitoring is currently running.')
    else:
        c.chat_data['monitor_prs_job'].schedule_removal()
        del c.chat_data['monitor_prs_job']
        u.message.reply_text('Stopped monitoring PRs.')

def main():
    updater = Updater(t_token)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("monitor_prs", monitor_prs))
    dispatcher.add_handler(CommandHandler("stop_monitor", stop_monitor))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
