# Taylor: what we need to turn your trading into a bot

Taylor,

Thanks for the recording, it worked and it was useful. I went through it frame by frame
with the transcript, and a lot of what you do is already close to rules: small entry on a
VWAP touch, size up on a MACD cross, add on the dip, "see green, take green", no stop.

Here is the one thing that matters before we build anything: **the bot can only learn
rules, not intuition.** Every time you would say "I felt like it" or "I just know", the
bot has nothing to do. So for each question below, please answer with a rule you could
hand to a stranger who has never traded, and they would take the exact same trade you
would. If the honest answer is "it depends", tell us what it depends on. If you really
do not have a rule for something, say that too. "No rule" is a useful answer. "Feel" is not.

Short answers are fine. Numbers are better than adjectives ("6 contracts" beats "a bit
more", "3 points" beats "a little").

## 1. Your setup

1. What instrument do you actually trade, and what do you look at for signals? From the
   video it looks like you trade MNQ but read ES on a 1-minute Heikin-Ashi chart. Is that
   right? Do you ever trade ES/MES or NQ full size?
2. List every indicator on your charts with its settings. For each one: name, timeframe,
   and the numbers (for example "MACD 12 / 26 / 9 on the 1-minute ES Heikin-Ashi").
   Please include:
   - MACD (lengths, which chart)
   - VWAP (session VWAP? anchored to what?)
   - The Tiki On Balance Volume and Tiki WAE panels (what are they, what settings)
   - The boxes / zones drawn on the WealthCharts chart (what draws them, what do the
     colours mean)
   - Heikin-Ashi (which charts use it, which use normal candles)
   - Anything else on screen, even if you do not look at it much
3. What times of day do you trade, and are there times you never trade? You called
   midday "lunch monkey time" but traded through it. Is there a rule, or is it a mood?
4. Do you check anything before the session (news, overnight range, previous day
   high/low)? If yes, what exactly, and what makes you not trade that day?

## 2. Entry: when do you go in?

5. Write the entry as an if-then. Example of the shape we need:
   "IF price touches VWAP from above on the 1-minute AND the Heikin-Ashi candle is a doji
   THEN buy 1 MNQ at the ask."
   What are the actual conditions? All of them, including the ones that feel obvious.
6. Is there a separate, stronger entry? In the video you said a MACD cross up makes you
   "take these a little stronger" and you took 6 contracts. What exactly has to be true
   for the 6-lot entry versus the 1-lot entry?
7. Do you only go long, or do you short as well? If you short, what is the mirror rule,
   or is it different?
8. What stops you from entering even when the signal is there? (Too far from VWAP,
   already up a lot on the day, just took a loss, size of the last candle, anything.)

## 3. Adding: the part we need most

This is the piece a bot cannot guess, and it is the piece that decides whether the account
survives. In the video you went 5 to 10 contracts, and later 6 to 12 to 19, each time
price moved against you.

9. When price goes against you, what makes you add? A number of points against? A
   candle colour? A touch of a level? Time?
10. How many contracts do you add each time, and does that number change with how far
    you are offside?
11. How many times will you add on one trade? Is there a maximum position size, ever?
    (In the video the peak was 19 MNQ.)
12. Is there a point where you stop adding and just wait? What defines it?

## 4. Exit: "see green, take green"

13. "Green" means the open P/L on the position is positive. Do you exit when it is
    positive by any amount, or is there a minimum (dollars or points)?
14. Do you exit all at once or in pieces? In the video you went 10 to 3 to 1 to flat.
    What decides each piece?
15. When do you leave a runner, how big is it, and what gets you out of the runner?
16. If a trade is big and finally gets back to green after a lot of adds, do you take the
    whole thing off at breakeven, or hold for a target?

## 5. Losses: the question nobody likes

You said on the video "still not using a stop" and "that was a bad trade". For a bot
this is the single most important section. If the answer is "there is no rule", say so,
and we will have to design one together before anything goes live.

17. When do you give up on a trade and take the loss? Points against? Dollars? Time in
    the trade? A level breaking? A candle pattern?
18. What is the most you have lost on one trade, and on one day? What happened?
19. Is there a daily loss number after which you stop for the day? What is it?
20. What is the biggest position you have ever been in, and how far offside did it get?

## 6. Sizing and the account

21. How do you decide the starting size on a trade? Is it fixed, or based on the
    account, the day's P/L, or how sure you feel?
22. What is the daily profit target, if any, and do you stop when you hit it? (You
    mentioned "3%" on the recording. 3% of what, and is that per day?)
23. The prop account has a $4,500 trailing drawdown. Does that number change anything
    about how you trade, or do you trade the same regardless?

## 7. Data, please

24. From Tradovate, export your fills (Reports, then Fills, then export to CSV) for as far
    back as it allows, and send the file. Every fill with its timestamp. This is the
    truth we test the rules against; the recordings show us the good minutes, the fills
    show us everything.
25. If you can export 1-minute chart data for NQ or MNQ and ES from Tradovate or
    WealthCharts, send that as CSV too. If not, tell us what you use and we will source it.
26. Keep recording sessions the way you did. The ones that matter most are the bad days.
    A recording of a losing day teaches the bot more than ten winning ones.

## 8. One last check

Read back through your answers. Anywhere you wrote "usually", "sometimes", "if it feels
right", "when it looks like", or "depending", that is intuition. Either replace it with a
number or a condition, or mark it clearly as "no rule yet". We will build from what is
left, test it on real data including the days it would have failed, and show you the
results before any money goes near it.

Thanks,
Ron
