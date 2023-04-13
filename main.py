import os
import time
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from github import Github, GithubException
import openai
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()
t_token = os.getenv("TELEGRAM_BOT_TOKEN")
gh_token = os.getenv("GITHUB_ACCESS_TOKEN")
oai_key = os.getenv("OPENAI_API_KEY")

# Initialize APIs
github_api = Github(gh_token)
openai.api_key = oai_key

# List of GitHub organizations to monitor
gh_orgs = [
    'ethereum', 'bitcoin', 'yearn', 'makerdao', 'curvefi', 'uniswap',
    'sushiswap', 'compound-finance', 'aave', 'balancer-labs',
    'alchemix-finance', 'redacted-cartel', 'manifoldfinance'
]

# Set the interval to run every 65 minutes (to avoid GitHub's rate limit)
run_every = 60 * 65

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Hi! I am a GitHub PR monitoring bot. Use the /monitor_prs command to start monitoring PRs!')

class PRMonitor:
    def __init__(self):
        self.state_per_chat = {}

    def recursive_summarize(self, summaries):
        if len(summaries) == 1:
            return summaries[0]

        new_summaries = []
        for i in range(0, len(summaries), 4):
            combined_summaries = ' '.join(summaries[i:i + 4])

            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an AI assistant that can generate a brief and coherent summary based on multiple summaries made from parts of the same corpus of text. Your task is to provide a single, easily understandable summary that highlights the most important information from the given summaries, make it short and only up to 500 characters"
                    },
                    {
                        "role": "user",
                        "content": f"Summarize the following summaries:\n\n{combined_summaries}"
                    }
                ]
            )
            new_summaries.append(response.choices[0].message['content'])
            time.sleep(1)

        return self.recursive_summarize(new_summaries)

    def monitor_prs(self, context: CallbackContext):
        chat_id = context.job.context
        if chat_id not in self.state_per_chat:
            self.state_per_chat[chat_id] = {'seen_prs': set(), 'last_pr_timestamp': time.time() - run_every}
        last_pr_timestamp = self.state_per_chat[chat_id]['last_pr_timestamp']

        for org_name in gh_orgs:
            print("Checking " + org_name + " for PRs in " + len(org.get_repos()) + " repos...")
            try:
                org = github_api.get_organization(org_name)
            except GithubException as e:
                print(f"Error fetching organization {org_name}: {e}")
                continue

            for repo in org.get_repos():
                
                try:
                    pr_list = repo.get_pulls(state='open')
                except GithubException as e:
                    print(f"Error fetching PRs for repo {repo.name}: {e}")
                    continue

                for pr in pr_list:
                    if pr.id in self.state_per_chat[chat_id]['seen_prs'] or pr.created_at.timestamp() <= last_pr_timestamp:
                        continue

                    print(f"Summarizing new PR: {pr.html_url}")

                    pr_title = pr.title
                    pr_desc = pr.body
                    diff_resp = requests.get(pr.patch_url)
                    diff_txt = diff_resp.text
                    cm_msgs = "\n".join([cm.commit.message for cm in pr.get_commits()])
                    full_txt = f"Title: {pr_title}\nDescription: {pr_desc}\nCommit messages: {cm_msgs}\nDiff: {diff_txt}"
                    max_chars = 7500
                    chunks = [full_txt[i:i + max_chars] for i in range(0, len(full_txt), max_chars)]

                    try:
                        summaries = []
                        response = None

                        for chunk in chunks:
                            response = openai.ChatCompletion.create(
                                model="gpt-3.5-turbo",
                                messages=[
                                    {
                                        "role": "system",
                                        "content": "You are an AI assistant specialized in summarizing GitHub pull requests. Your task is to provide concise and informative summaries that help users understand the most important and relevant changes made in the code. Avoid mentioning less important details, make it short and only up to 500 characters, focus on explaining code changes."
                                    },
                                    {
                                        "role": "user",
                                        "content": f"Summarize the following PR information, focusing on the most important changes:\n\n{chunk}"
                                    }
                                ]

                            )
                            summaries.append(response.choices[0].message['content'])
                            time.sleep(1)

                        if len(chunks) > 1:
                            final_summary = self.recursive_summarize(summaries)
                        else:
                            final_summary = summaries[0]

                        print(f"Sending summary: {final_summary}")

                    except Exception as e:
                        print(f"Error generating summary with OpenAI API: {e}")
                        final_summary = f"{pr_title}\n\n_Summary unavailable, could not reach OpenAI._"
                        try:
                            context.bot.send_message(chat_id, f"*{org_name} / {repo.name}*\n\n{final_summary}\n\n🔗 {pr.html_url}", parse_mode='Markdown', disable_web_page_preview=True)
                        except Exception as e:
                            print(f"Error sending message: {e}")

                    else:
                        try:
                            context.bot.send_message(chat_id, f"*{org_name} / {repo.name}*\n\n{final_summary}\n\n🔗 {pr.html_url}", parse_mode='Markdown', disable_web_page_preview=True)
                        except Exception as e:
                            print(f"Error sending message: {e}")

                    self.state_per_chat[chat_id]['seen_prs'].add(pr.id)
        self.state_per_chat[chat_id]['last_pr_timestamp'] = time.time()

def monitor_prs(update: Update, context: CallbackContext) -> None:
    if update.effective_chat.id != -1001798829382:
        update.message.reply_text("Sorry, this bot is limited to a specific group.")
        return

    interval = run_every
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
    updater = Updater(t_token)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("monitor_prs", monitor_prs))
    dispatcher.add_handler(CommandHandler("stop_monitor", stop_monitor))

    updater.start_polling()

    chat_id = -1001798829382
    interval = run_every
    pr_monitor = PRMonitor()
    updater.job_queue.run_repeating(pr_monitor.monitor_prs, interval, context=chat_id)

    updater.idle()

if __name__ == "__main__":
    main()
