import os
import time
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from github import Github
import openai
from dotenv import load_dotenv
import requests

load_dotenv()
t_token = os.getenv("TELEGRAM_BOT_TOKEN")
gh_token = os.getenv("GITHUB_ACCESS_TOKEN")
oai_key = os.getenv("OPENAI_API_KEY")
github_api = Github(gh_token)
openai.api_key = oai_key
gh_orgs = ['ethereum', 'bitcoin', 'yearn', 'makerdao', 'curvefi', 'sniswap', 'sushiswap', 'compound-finance', 'aave', 'balancer-labs', 'alchemix-finance', 'convex-eth']

def start(u: Update, c: CallbackContext) -> None:
    u.message.reply_text('Hi! I am a GitHub PR monitoring bot. Use the /monitor_prs command to start monitoring PRs!')

class PRMonitor:
    def __init__(self):
        self.sp = {}

    def m_prs(self, c: CallbackContext):
        cid = c.job.context
        if cid not in self.sp:
            self.sp[cid] = {'s_prs': set(), 'm_start': time.time()}
        m_start = self.sp[cid]['m_start']

        print("Checking PRs...")

        for o_name in gh_orgs:
            org = github_api.get_organization(o_name)
            for repo in org.get_repos():
                for pr in repo.get_pulls(state='open'):
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
                    for chunk in chunks:
                        res = openai.ChatCompletion.create(
                            model="gpt-3.5-turbo",
                            messages=[
                                {"role": "system", "content": "You are a helpful assistant."},
                                {"role": "user", "content": f"Summarize the following PR information:\n\n{chunk}"}
                            ]
                        )
                        summaries.append(res.choices[0].message['content'])

                    res = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": "You are a helpful assistant."},
                            {"role": "user", "content": f"Summarize the following summaries:\n\n{' '.join(summaries)}"}
                        ]
                    )
                    f_summary = res.choices[0].message['content']

                    print(f"Sending summary: {f_summary}")

                    c.bot.send_message(cid, f"*PR Summary:* {f_summary}\n\n*PR Link:* {pr.html_url}", parse_mode='Markdown')
                    self.sp[cid]['s_prs'].add(pr.id)

def monitor_prs(u: Update, c: CallbackContext) -> None:
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
