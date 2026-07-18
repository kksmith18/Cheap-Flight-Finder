"""Data source boundary. ALL fast-flights usage must go through get_cheapest_fare.

Swapping providers later (Duffel, SerpApi, ...) means touching only this file.
"""

from dataclasses import dataclass

from fast_flights import FlightQuery, Passengers, create_query, get_flights
from fast_flights.exceptions import FlightsNotFound


@dataclass
class FareResult:
    price: int
    airline: str
    origin: str
    destination: str
    depart_date: str
    return_date: str
    google_flights_url: str


def get_cheapest_fare(
    origin: str, destination: str, depart_date: str, return_date: str
) -> FareResult | None:
    """Cheapest roundtrip economy fare for one adult, or None if no flights exist.

    depart_date/return_date are "YYYY-MM-DD" strings. Raises on request/parse
    failure (network errors, blocked scraper, etc.) so callers can count it as
    a failed query; returns None only when the search legitimately found no
    flights.
    """
    query = create_query(
        flights=[
            FlightQuery(date=depart_date, from_airport=origin, to_airport=destination),
            FlightQuery(date=return_date, from_airport=destination, to_airport=origin),
        ],
        seat="economy",
        trip="round-trip",
        passengers=Passengers(adults=1),
        language="en",
        currency="USD",
    )

    try:
        results = get_flights(query)
    except FlightsNotFound:
        return None

    if not results:
        return None

    cheapest = min(results, key=lambda f: f.price)
    return FareResult(
        price=cheapest.price,
        airline=", ".join(cheapest.airlines),
        origin=origin,
        destination=destination,
        depart_date=depart_date,
        return_date=return_date,
        google_flights_url=query.url(),
    )
