---
title: Weekly sync — 11 Oct
date: 2026-10-11
author: Priya Nair
attendees: [Priya Nair, Aarav Mehta, Sneha Kulkarni, Kabir Singh]
---

# Weekly sync — 11 Oct

## Hosting

The API moved to Railway on 3 Oct. Render's free tier went to sleep and the first scan at
the check-in rehearsal took almost a minute. Railway is $5 a month.

## Payments

Webhooks keep failing on campus Wi-Fi. Aarav is switching to polling: the return page will
check the payment status every 60 seconds until it's confirmed. A nightly job will catch
anything missed.

## Bots

Rate limiting on registration went in after the bot sign-ups on 2 Oct.
