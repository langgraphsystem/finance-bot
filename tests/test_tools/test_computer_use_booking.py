"""Tests for hotel-specific computer use parsing helpers."""

from src.tools.computer_use_booking import (
    _parse_cu_booking_result,
    _parse_cu_hotel_results,
)


def test_parse_cu_hotel_results_extracts_json_array():
    raw = """
    Here are the hotels:
    [
      {
        "name": "Hotel One",
        "price_per_night": "$180",
        "rating": "8.9",
        "review_count": "1204",
        "distance": "0.4 mi from center",
        "cancellation": "Free cancellation",
        "description": "Large room",
        "url": "https://booking.com/hotel/one"
      }
    ]
    """

    result = _parse_cu_hotel_results(raw)

    assert len(result) == 1
    assert result[0]["name"] == "Hotel One"
    assert result[0]["url"] == "https://booking.com/hotel/one"


def test_parse_cu_booking_result_ready_to_book():
    raw = """
    {
      "status": "READY_TO_BOOK",
      "total_price": "$640",
      "room_type": "Standard Double Room",
      "cancellation_policy": "Free cancellation until Mar 20",
      "payment_type": "pay_at_hotel",
      "saved_card": "Visa ****4242",
      "booking_url": "https://booking.com/checkout",
      "notes": "Breakfast included"
    }
    """

    result = _parse_cu_booking_result(raw)

    assert result["status"] == "READY_TO_BOOK"
    assert result["total_price"] == "$640"
    assert result["booking_url"] == "https://booking.com/checkout"
