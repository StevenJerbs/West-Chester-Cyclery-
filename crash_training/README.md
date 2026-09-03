# crash_training

Training footage copied from the mtbkin sourcing pipeline (`pipeline_b/sourcing/sources.txt`). Videos are git-lfs.
Each video ships with its YouTube closed captions (`<id>.captions.vtt`), a cleaned timestamped transcript
(`<id>.transcript.txt`), and where useful a caption-derived segment map (`<id>.segments.json`).

| Video | Source | Notes |
|---|---|---|
| `friday_fails_2025_1080p_hdspQwUno_Q.mp4` | https://youtu.be/hdspQwUno_Q | Pinkbike, 30 Minutes Of The Best (And Worst) Fails From 2025. 1080p30, 30m08s. Crash compilation, negative examples. |
| `asa_vermette_vs_avg_rider_Y50K3ZZEdVY.mp4` | https://youtu.be/Y50K3ZZEdVY | Pinkbike, Asa Vermette vs. An Average Rider. 1080p25, 10m08s. Pro vs average on the same track, paired A/B footage 2:25-3:52. |
| `loic_bruni_vs_avg_rider_JQXt8o4FMys.mp4` | https://youtu.be/JQXt8o4FMys | Pinkbike, Loic Bruni vs Average Rider. 1080p25, 18m56s. Pro vs average on the Andorra World Cup track, paired A/B footage 7:06-9:29. |
| `windrock_2026_redbull_tn_national_iWW26z6MqSQ.mp4` | https://youtu.be/iWW26z6MqSQ | Windrock Bike Park, 2026 Red Bull Tennessee National Downhill Race. 1080p24, 1h05m53s. Full pro women and pro men finals broadcast; many pro riders on the same features, plus four narrated crashes. |

## Rider ID cues for the A/B videos

- Asa Vermette (A, pro): black Fox gloves. Host / average rider (B): no gloves, wrist watch, rental bike.
- Loic Bruni (A, pro) vs host (B, rented DH bike): visual cues not yet recorded.

## Segment maps

`*.segments.json` list time ranges with the rider on screen, section type, and the time gaps stated in the narration.
Best suspension-kinematics contrasts: Asa video section 3 (3:24-3:52, G-out compression) and Bruni video sections 1-3
(rock garden entries and root gaps, ~4-5 s and up to 50% speed difference). Windrock crash timestamps are in the
`crashes` list of its segment map (Pinkerton ~42:29, Gwin ~60:24).

Timestamps come from caption narration, not shot cuts. Refine against a scene list before slicing.
