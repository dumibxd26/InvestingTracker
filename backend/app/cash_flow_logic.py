from calendar import monthrange
from datetime import date

from app.models import Recurrence

MONTHS_PER_OCCURRENCE = {
    Recurrence.MONTHLY: 1,
    Recurrence.QUARTERLY: 3,
    Recurrence.ANNUAL: 12,
}


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def occurrence_dates(
    recurrence: Recurrence,
    start_date: date,
    end_date: date | None,
    from_date: date,
    through_date: date,
) -> list[date]:
    if through_date < from_date:
        return []

    if recurrence == Recurrence.ONE_TIME:
        if from_date <= start_date <= through_date and (end_date is None or start_date <= end_date):
            return [start_date]
        return []

    months_per_occurrence = MONTHS_PER_OCCURRENCE[recurrence]
    if start_date < from_date:
        months_since_start = (
            (from_date.year - start_date.year) * 12 + from_date.month - start_date.month
        )
        occurrence_number = max(
            0,
            (months_since_start + months_per_occurrence - 1) // months_per_occurrence,
        )
    else:
        occurrence_number = 0

    occurrence = add_months(start_date, occurrence_number * months_per_occurrence)
    while occurrence < from_date:
        occurrence_number += 1
        occurrence = add_months(start_date, occurrence_number * months_per_occurrence)

    dates: list[date] = []
    while occurrence <= through_date and (end_date is None or occurrence <= end_date):
        dates.append(occurrence)
        occurrence_number += 1
        occurrence = add_months(start_date, occurrence_number * months_per_occurrence)
    return dates
