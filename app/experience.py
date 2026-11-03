"""Years of experience: Gemini lists the jobs, this code counts them."""
from pydantic import BaseModel


class Job(BaseModel):
    title: str
    start: str           # "2023" or "2023-07"
    end: str | None      # empty = still working there
    internship: bool
    part: int            # the CV part it was read from


ENGLISH = {
    "years": "Experience: {y} years",
    "below": "; {gap} year(s) below the minimum of {n}",
    "above": "; {gap} year(s) above the maximum of {n}",
    "now": "Present",
    "intern": "internship, not counted",
    "unreadable": "Could not read the job dates; check them by hand.",
}

ARABIC = {
    "years": "سنوات الخبرة: {y}",
    "below": "؛ أقل من الحد الأدنى ({n}) بفارق {gap}",
    "above": "؛ أكثر من الحد الأعلى ({n}) بفارق {gap}",
    "now": "حالياً",
    "intern": "تدريب، لا يُحتسب",
    "unreadable": "تعذّرت قراءة تواريخ الوظائف؛ يُرجى مراجعتها يدوياً.",
}


def month_number(date, today, has_month):
    """Turn a date into a number of months, so two dates can be subtracted."""
    if not date:                          # still working there
        year = today.year
        month = today.month if has_month else 1
    elif "-" in date:                     # "2023-07"
        year, month = date.split("-")
    else:                                 # "2023": counts from January
        year, month = date, 1
    return int(year) * 12 + int(month)


def count_years(jobs, today):
    """Count the months worked. A month with two jobs is counted once."""
    months_worked = set()
    for job in jobs:
        has_month = "-" in job.start
        first = month_number(job.start, today, has_month)
        last = month_number(job.end, today, has_month)
        months_worked.update(range(first, last))
    return round(len(months_worked) / 12, 1)


def check(jobs, min_years, max_years, today, arabic):
    """Return (fit, reason)."""
    text = ARABIC if arabic else ENGLISH

    # 1. every job, without internships
    counted = [job for job in jobs if not job.internship]

    # 2. count the years
    try:
        years = count_years(counted, today)
    except ValueError:
        return "partial", text["unreadable"]

    # 3. compare with the limits
    gap = 0
    note = ""
    if min_years and years < min_years:
        gap = min_years - years
        note = text["below"].format(n=min_years, gap=f"{gap:g}")
    if max_years and years > max_years:
        gap = years - max_years
        note = text["above"].format(n=max_years, gap=f"{gap:g}")

    if gap == 0:
        fit = "full"
    elif gap <= 1:
        fit = "partial"
    else:
        fit = "none"

    # 4. write the reason: the years, then one line per job
    parts = sorted(set(job.part for job in jobs))          # the CV parts, printed like [12, 13]
    reason = text["years"].format(y=f"{years:g}") + note + f" {parts}."
    for job in jobs:
        end = job.end or text["now"]
        reason += f"\n{job.title}: {job.start} – {end}"
        if job.internship:
            reason += f" ({text['intern']})"

    return fit, reason