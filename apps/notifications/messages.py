"""Notification texts per language. Swahili should be reviewed by a native speaker.

Keep SMS-bound texts to plain ASCII: one non-GSM character (curly quote, emoji)
cuts an SMS segment from 160 to 70 characters and doubles the cost."""

MESSAGES = {
    "booking.requested": {
        "en": ("New job request", "{client} requested {category} ({ref})."),
        "sw": ("Ombi jipya la kazi", "{client} ameomba huduma ya {category} ({ref})."),
    },
    "booking.accepted": {
        "en": ("Request accepted", "{fundi} accepted your request {ref}."),
        "sw": ("Ombi limekubaliwa", "{fundi} amekubali ombi lako {ref}."),
    },
    "booking.declined": {
        "en": ("Request declined", "{fundi} could not take your request {ref}."),
        "sw": ("Ombi limekataliwa", "{fundi} hawezi kupokea ombi lako {ref}."),
    },
    "booking.expired": {
        "en": ("Request expired", "Your request {ref} was not answered in time."),
        "sw": ("Ombi limeisha muda", "Ombi lako {ref} halikujibiwa kwa wakati."),
    },
    "booking.cancelled": {
        "en": ("Job cancelled", "Job {ref} has been cancelled."),
        "sw": ("Kazi imeghairiwa", "Kazi {ref} imeghairiwa."),
    },
    "booking.started": {
        "en": ("Job started", "{fundi} has started job {ref}."),
        "sw": ("Kazi imeanza", "{fundi} ameanza kazi {ref}."),
    },
    "booking.completed": {
        "en": ("Job completed", "{fundi} marked job {ref} as done. Please confirm and leave a review."),
        "sw": ("Kazi imekamilika", "{fundi} amekamilisha kazi {ref}. Tafadhali thibitisha na utoe tathmini."),
    },
    "booking.disputed": {
        "en": ("Job disputed", "A problem was reported on job {ref}. Our team will contact you."),
        "sw": ("Kuna malalamiko", "Tatizo limeripotiwa kwenye kazi {ref}. Timu yetu itawasiliana nawe."),
    },
    "verification.approved": {
        "en": ("Identity verified", "Your identity has been verified."),
        "sw": ("Utambulisho umethibitishwa", "Hongera! Utambulisho wako umethibitishwa."),
    },
    "verification.rejected": {
        "en": ("Verification unsuccessful", "We could not verify your identity: {reason}. Please submit again."),
        "sw": ("Uthibitisho haukufanikiwa", "Hatukuweza kuthibitisha utambulisho wako: {reason}. Tafadhali tuma tena."),
    },
    "verification.reverification_required": {
        "en": ("Please verify again", "Please verify your identity again to stay visible to clients."),
        "sw": ("Thibitisha tena", "Tafadhali thibitisha utambulisho wako tena ili uendelee kuonekana kwa wateja."),
    },
    "fundi.suspended": {
        "en": ("Fundi profile suspended", "Your fundi profile has been suspended. Contact support for details."),
        "sw": ("Wasifu wa fundi umesimamishwa", "Wasifu wako wa fundi umesimamishwa. Wasiliana nasi kwa maelezo."),
    },
}


def render(kind: str, language: str, **context) -> tuple[str, str]:
    texts = MESSAGES[kind]
    title, body = texts.get(language) or texts["en"]
    return title, body.format(**context)
