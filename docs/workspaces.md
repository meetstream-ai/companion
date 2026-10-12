# Workspaces and export

## Workspaces

One account can belong to several workspaces and switch between them from the
picker in the top bar (the workspace name next to the theme toggle).

Everything is scoped to the workspace you currently have open - meetings,
notes, memory, action items - so switching changes what you see. Your role
travels with the workspace too: you can own one and be a plain member of
another.

From the workspace picker you can **create** another workspace (you own it) or
**join** one with a code (you are a member - ownership stays with whoever made
it). Both attach to the account you are already signed in as, so there is no
second login to keep track of.

Your first workspace is created for you at sign-up. Nothing needs converting to
share it: hand someone the join code from **Members**, approve their request
when it appears there, and it becomes a shared workspace. Owners decide what
members may do there — add, edit, delete, manage agents, export, invite — from
the same page.

A join code is a request, not a key. Someone who uses it - at sign-up, or
from the picker while already signed in - is listed under **Requests to
join** on the owner's Members page and sees nothing of the workspace until an
owner clicks **Approve**; **Decline** drops the request. Adding someone
yourself with **Add member** skips this, since you are the one letting them
in. The code keeps working until you replace it, so anyone who has ever been
sent one can still ask; **New code** on the Members page retires it on the
spot, and people already in the workspace stay. Owners can also **rename** the
workspace there, or **delete** it once the other members have been removed
and there is another workspace to land in - deletion takes every meeting,
note, document and memory in it with it, and cannot be undone.

On the desktop app a workspace lives in one database, and a code only means
something on that database. Joining - from the setup wizard, the picker or
**Create account** - therefore asks for the team's connection string first and
the code second, and checks that the code exists on that database before
anything is switched. Leave the connection string blank when the workspace is
on the database the app already uses, which is always the case on a shared
server.

<div align="center">
<img src="media/workspaces.gif" alt="On the Members page an owner switches on Delete content and Invite people for members, then opens the workspace picker, creates a second workspace and switches back" width="900" />
</div>

What is shared and what is not:

| Shared across the workspace | Stays yours alone |
| --- | --- |
| Meetings, transcripts, memories, action items | Your MeetStream API key (bots bill to you) |
| Notes, folders, documents, knowledge graph | Your agent |
| Search and Ask AI results | Your LLM provider and key (per install) - unless the owner unified it, below |

## AI provider: yours, or one for the whole workspace

Each install has its own AI settings, so by default five people on one shared
database each use whatever they set up - their key, their bill, their model.
An owner can instead pick **One provider for everyone** on the Members page
and set it there; every member's app then uses that provider in this
workspace, so summaries read the same whoever imported the meeting. The
choice travels with the workspace (it is stored in the database with it),
members see which applies on their Members and Settings pages, and their own
settings still apply to their other workspaces.

## Export

Your notes and meetings come back out in formats that outlive the app.

| Where | What you get |
| --- | --- |
| A note (Notebook -> export) | `.md` with YAML front matter, or `.json` |
| A meeting (Meetings -> Export) | `.md` with summary, decisions, action items and transcript, or `.json` |
| Everything (Settings -> General) | `.zip` of Markdown that keeps your folder tree, or one `.json` |

Markdown is written for reading and for dropping straight into Obsidian or
Notion - front matter carries the title, tags, folder and dates. JSON is the
lossless one: ids, metadata and the raw note text, so an export can be
processed or re-imported by something else.
