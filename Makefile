.PHONY: check demo

check:
	python3 -m unittest -v test_iphone_control
	python3 -m py_compile coordinates.py iphone_control.py
	python3 -m py_compile gps_mock.py
	python3 -m py_compile gps_mock_app.py
	python3 gps_mock.py point --lat 31.2304 --lon 121.4737 -o /tmp/gps-mock-check.gpx
	python3 gps_mock.py validate /tmp/gps-mock-check.gpx

demo:
	python3 gps_mock.py point --lat 31.2304 --lon 121.4737 -o mock-location.gpx
