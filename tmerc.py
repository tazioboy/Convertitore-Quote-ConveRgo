"""Proiezione trasversa di Mercator (serie di Krueger, precisione sub-millimetrica nel fuso)."""
import math

ELLIPSOIDS = {
    "GRS80": (6378137.0, 1.0 / 298.257222101),
    "INTL": (6378388.0, 1.0 / 297.0),
}


class TMerc:
    def __init__(self, ellps, lon0_deg, k0=0.9996, x0=500000.0, y0=0.0):
        a, f = ELLIPSOIDS[ellps]
        n = f / (2 - f)
        self.e = math.sqrt(f * (2 - f))
        self.lon0 = math.radians(lon0_deg)
        self.k0, self.x0, self.y0 = k0, x0, y0
        n2, n3, n4, n5, n6 = n ** 2, n ** 3, n ** 4, n ** 5, n ** 6
        self.A = a / (1 + n) * (1 + n2 / 4 + n4 / 64 + n6 / 256)
        self.alpha = [
            n / 2 - 2 * n2 / 3 + 5 * n3 / 16 + 41 * n4 / 180 - 127 * n5 / 288 + 7891 * n6 / 37800,
            13 * n2 / 48 - 3 * n3 / 5 + 557 * n4 / 1440 + 281 * n5 / 630 - 1983433 * n6 / 1935360,
            61 * n3 / 240 - 103 * n4 / 140 + 15061 * n5 / 26880 + 167603 * n6 / 181440,
            49561 * n4 / 161280 - 179 * n5 / 168 + 6601661 * n6 / 7257600,
            34729 * n5 / 80640 - 3418889 * n6 / 1995840,
            212378941 * n6 / 319334400]
        self.beta = [
            n / 2 - 2 * n2 / 3 + 37 * n3 / 96 - n4 / 360 - 81 * n5 / 512 + 96199 * n6 / 604800,
            n2 / 48 + n3 / 15 - 437 * n4 / 1440 + 46 * n5 / 105 - 1118711 * n6 / 3870720,
            17 * n3 / 480 - 37 * n4 / 840 - 209 * n5 / 4480 + 5569 * n6 / 90720,
            4397 * n4 / 161280 - 11 * n5 / 504 - 830251 * n6 / 7257600,
            4583 * n5 / 161280 - 108847 * n6 / 3991680,
            20648693 * n6 / 638668800]
        self.delta = [
            2 * n - 2 * n2 / 3 - 2 * n3 + 116 * n4 / 45 + 26 * n5 / 45 - 2854 * n6 / 675,
            7 * n2 / 3 - 8 * n3 / 5 - 227 * n4 / 45 + 2704 * n5 / 315 + 2323 * n6 / 945,
            56 * n3 / 15 - 136 * n4 / 35 - 1262 * n5 / 105 + 73814 * n6 / 2835,
            4279 * n4 / 630 - 332 * n5 / 35 - 399572 * n6 / 14175,
            4174 * n5 / 315 - 144838 * n6 / 6237,
            601676 * n6 / 22275]

    def forward(self, lat_deg, lon_deg):
        """(lat, lon) gradi -> (Est, Nord) metri."""
        phi = math.radians(lat_deg)
        dl = math.radians(lon_deg) - self.lon0
        e = self.e
        s = math.sin(phi)
        t = math.sinh(math.atanh(s) - e * math.atanh(e * s))
        xi0 = math.atan2(t, math.cos(dl))
        eta0 = math.atanh(math.sin(dl) / math.sqrt(1 + t * t))
        xi, eta = xi0, eta0
        for j, al in enumerate(self.alpha, 1):
            xi += al * math.sin(2 * j * xi0) * math.cosh(2 * j * eta0)
            eta += al * math.cos(2 * j * xi0) * math.sinh(2 * j * eta0)
        return self.x0 + self.k0 * self.A * eta, self.y0 + self.k0 * self.A * xi

    def inverse(self, east, north):
        """(Est, Nord) metri -> (lat, lon) gradi."""
        xi0 = (north - self.y0) / (self.k0 * self.A)
        eta0 = (east - self.x0) / (self.k0 * self.A)
        xi, eta = xi0, eta0
        for j, b in enumerate(self.beta, 1):
            xi -= b * math.sin(2 * j * xi0) * math.cosh(2 * j * eta0)
            eta -= b * math.cos(2 * j * xi0) * math.sinh(2 * j * eta0)
        chi = math.asin(math.sin(xi) / math.cosh(eta))
        phi = chi
        for j, d in enumerate(self.delta, 1):
            phi += d * math.sin(2 * j * chi)
        lon = self.lon0 + math.atan2(math.sinh(eta), math.cos(xi))
        return math.degrees(phi), math.degrees(lon)
