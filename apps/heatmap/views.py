import json
from django.shortcuts import render
from django.db.models import Count
from apps.callers.models import CallSession
from datetime import date, timedelta


# Static lat/lng lookup for known Philippine cities/municipalities
LOCATION_COORDS = {
    # NCR
    "Manila": (14.5995, 120.9842), "Quezon City": (14.6760, 121.0437),
    "Makati": (14.5547, 121.0244), "Pasig": (14.5764, 121.0851),
    "Taguig": (14.5243, 121.0792), "Mandaluyong": (14.5794, 121.0359),
    "Marikina": (14.6507, 121.1029), "Pasay": (14.5378, 121.0014),
    "Caloocan": (14.6499, 120.9837), "Las Piñas": (14.4453, 120.9832),
    "Muntinlupa": (14.4081, 121.0415), "Parañaque": (14.4793, 121.0198),
    "Valenzuela": (14.7011, 120.9830), "Malabon": (14.6625, 120.9571),
    "Navotas": (14.6667, 120.9417), "Pateros": (14.5453, 121.0683),
    "San Juan": (14.6019, 121.0355),
    # Region VII - Central Visayas
    "Cebu City": (10.3157, 123.8854), "Mandaue City": (10.3236, 123.9223),
    "Lapu-Lapu City": (10.3103, 123.9494), "Talisay City": (10.2447, 123.8494),
    "Danao City": (10.5228, 124.0267), "Carcar City": (10.1062, 123.6394),
    "Toledo City": (10.3772, 123.6386), "Naga City Cebu": (10.2119, 123.7572),
    "Bogo City": (11.0511, 124.0053), "Minglanilla": (10.2428, 123.7997),
    "Consolacion": (10.3742, 123.9617), "Liloan": (10.3972, 123.9997),
    "Compostela": (10.4572, 124.0097), "Cordova": (10.2572, 123.9597),
    "Tagbilaran City": (9.6500, 123.8500), "Dumaguete City": (9.3068, 123.3054),
    # Region VI - Western Visayas
    "Iloilo City": (10.7202, 122.5621), "Bacolod City": (10.6765, 122.9509),
    "Roxas City": (11.5858, 122.7511), "Kalibo": (11.7058, 122.3644),
    "Passi City": (11.1058, 122.6394), "San Jose de Buenavista": (10.7558, 121.9394),
    # Region VIII - Eastern Visayas
    "Tacloban City": (11.2543, 125.0000), "Ormoc City": (11.0058, 124.6078),
    "Calbayog City": (12.0658, 124.5978), "Catbalogan": (11.7758, 124.8878),
    # Mindanao
    "Davao City": (7.1907, 125.4553), "Cagayan de Oro": (8.4542, 124.6319),
    "Zamboanga City": (6.9214, 122.0790), "General Santos": (6.1164, 125.1716),
    "Iligan City": (8.2280, 124.2452), "Butuan City": (8.9475, 125.5406),
    "Cotabato City": (7.2236, 124.2461), "Pagadian City": (7.8278, 123.4378),
    # Luzon
    "Baguio City": (16.4023, 120.5960), "Angeles City": (15.1450, 120.5887),
    "Olongapo City": (14.8292, 120.2828), "San Fernando Pampanga": (15.0286, 120.6899),
    "Cabanatuan City": (15.4866, 120.9669), "San Jose Nueva Ecija": (15.7944, 121.1128),
    "Lipa City": (13.9411, 121.1631), "Batangas City": (13.7565, 121.0583),
    "Lucena City": (13.9373, 121.6170), "Naga City": (13.6192, 123.1814),
    "Legazpi City": (13.1391, 123.7438), "Daet": (14.1122, 122.9550),
    "Vigan City": (17.5747, 120.3869), "Laoag City": (18.1977, 120.5936),
    "Tuguegarao City": (17.6132, 121.7270), "Ilagan City": (17.1486, 121.8892),
}

REGIONS = [
    ("all", "All Regions"),
    ("NCR", "NCR – Metro Manila"),
    ("CAR", "CAR – Cordillera Administrative Region"),
    ("I", "Region I – Ilocos Region"),
    ("II", "Region II – Cagayan Valley"),
    ("III", "Region III – Central Luzon"),
    ("IV-A", "Region IV-A – CALABARZON"),
    ("IV-B", "Region IV-B – MIMAROPA"),
    ("V", "Region V – Bicol Region"),
    ("VI", "Region VI – Western Visayas"),
    ("VII", "Region VII – Central Visayas"),
    ("VIII", "Region VIII – Eastern Visayas"),
    ("IX", "Region IX – Zamboanga Peninsula"),
    ("X", "Region X – Northern Mindanao"),
    ("XI", "Region XI – Davao Region"),
    ("XII", "Region XII – SOCCSKSARGEN"),
    ("XIII", "Region XIII – Caraga"),
    ("BARMM", "BARMM – Bangsamoro"),
]

# Map cities to their region code
CITY_REGION = {
    # NCR
    "Manila": "NCR", "Quezon City": "NCR", "Makati": "NCR", "Pasig": "NCR",
    "Taguig": "NCR", "Mandaluyong": "NCR", "Marikina": "NCR", "Pasay": "NCR",
    "Caloocan": "NCR", "Las Piñas": "NCR", "Muntinlupa": "NCR", "Parañaque": "NCR",
    "Valenzuela": "NCR", "Malabon": "NCR", "Navotas": "NCR", "Pateros": "NCR",
    "San Juan": "NCR",
    # Region VII
    "Cebu City": "VII", "Mandaue City": "VII", "Lapu-Lapu City": "VII",
    "Talisay City": "VII", "Danao City": "VII", "Carcar City": "VII",
    "Toledo City": "VII", "Naga City Cebu": "VII", "Bogo City": "VII",
    "Minglanilla": "VII", "Consolacion": "VII", "Liloan": "VII",
    "Compostela": "VII", "Cordova": "VII", "Tagbilaran City": "VII",
    "Dumaguete City": "VII",
    # Region VI
    "Iloilo City": "VI", "Bacolod City": "VI", "Roxas City": "VI",
    "Kalibo": "VI", "Passi City": "VI", "San Jose de Buenavista": "VI",
    # Region VIII
    "Tacloban City": "VIII", "Ormoc City": "VIII", "Calbayog City": "VIII",
    "Catbalogan": "VIII",
    # Mindanao
    "Davao City": "XI", "Cagayan de Oro": "X", "Zamboanga City": "IX",
    "General Santos": "XII", "Iligan City": "X", "Butuan City": "XIII",
    "Cotabato City": "XII", "Pagadian City": "IX",
    # Luzon
    "Baguio City": "CAR", "Angeles City": "III", "Olongapo City": "III",
    "San Fernando Pampanga": "III", "Cabanatuan City": "III",
    "San Jose Nueva Ecija": "III", "Lipa City": "IV-A", "Batangas City": "IV-A",
    "Lucena City": "IV-A", "Naga City": "V", "Legazpi City": "V",
    "Daet": "V", "Vigan City": "I", "Laoag City": "I",
    "Tuguegarao City": "II", "Ilagan City": "II",
}

# Region center coordinates for map focus
REGION_CENTERS = {
    "all": (12.0, 122.0, 6),
    "NCR": (14.5995, 120.9842, 12),
    "CAR": (17.3510, 121.1720, 9),
    "I": (16.0832, 120.6200, 9),
    "II": (17.3510, 121.7720, 9),
    "III": (15.4755, 120.7118, 9),
    "IV-A": (14.1008, 121.0794, 9),
    "IV-B": (12.8797, 121.7740, 9),
    "V": (13.4213, 123.4136, 9),
    "VI": (11.0000, 122.5000, 9),
    "VII": (10.3157, 123.8854, 10),
    "VIII": (11.2543, 125.0000, 9),
    "IX": (7.8278, 123.4378, 9),
    "X": (8.4542, 124.6319, 9),
    "XI": (7.1907, 125.4553, 9),
    "XII": (6.2700, 124.6850, 9),
    "XIII": (8.9475, 125.5406, 9),
    "BARMM": (6.9214, 124.1800, 9),
}


def map_view(request):
    time_filter = request.GET.get('time', 'all')
    region_filter = request.GET.get('region', 'all')

    qs = CallSession.objects.select_related('caller')

    today = date.today()
    if time_filter == '24h':
        qs = qs.filter(session_call_date=today)
    elif time_filter == '7d':
        qs = qs.filter(session_call_date__gte=today - timedelta(days=7))
    elif time_filter == '30d':
        qs = qs.filter(session_call_date__gte=today - timedelta(days=30))

    aggregated = (
        qs.values('caller__caller_location', 'session_risk_assessment')
        .annotate(count=Count('session_id'))
    )

    # Build hotspot data grouped by location
    location_map = {}
    for row in aggregated:
        loc = row['caller__caller_location'] or ''
        if not loc:
            continue
        coords = LOCATION_COORDS.get(loc)
        if not coords:
            continue
        loc_region = CITY_REGION.get(loc, 'all')
        if region_filter != 'all' and loc_region != region_filter:
            continue
        if loc not in location_map:
            location_map[loc] = {'lat': coords[0], 'lng': coords[1], 'total': 0, 'high': 0, 'medium': 0, 'low': 0}
        risk = row['session_risk_assessment'].lower() if row['session_risk_assessment'] else ''
        location_map[loc]['total'] += row['count']
        if 'high' in risk:
            location_map[loc]['high'] += row['count']
        elif 'medium' in risk:
            location_map[loc]['medium'] += row['count']
        else:
            location_map[loc]['low'] += row['count']

    hotspots = [{'name': k, **v} for k, v in location_map.items()]

    # Build region-level aggregates for zoom-out view
    region_map = {}
    for h in hotspots:
        loc_region = CITY_REGION.get(h['name'], None)
        if not loc_region:
            continue
        region_label = dict(REGIONS).get(loc_region, loc_region)
        rc = REGION_CENTERS.get(loc_region)
        if not rc:
            continue
        if loc_region not in region_map:
            region_map[loc_region] = {'name': region_label, 'lat': rc[0], 'lng': rc[1], 'total': 0, 'high': 0, 'medium': 0, 'low': 0}
        region_map[loc_region]['total'] += h['total']
        region_map[loc_region]['high'] += h['high']
        region_map[loc_region]['medium'] += h['medium']
        region_map[loc_region]['low'] += h['low']

    regions_data = list(region_map.values())

    center = REGION_CENTERS.get(region_filter, REGION_CENTERS['all'])

    context = {
        'hotspots_json': json.dumps(hotspots),
        'regions_data_json': json.dumps(regions_data),
        'regions': REGIONS,
        'selected_region': region_filter,
        'selected_time': time_filter,
        'map_center_lat': center[0],
        'map_center_lng': center[1],
        'map_zoom': center[2],
    }
    return render(request, 'heatmap/map.html', context)
