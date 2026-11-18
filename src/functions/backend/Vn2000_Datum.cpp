#include "functions/backend/Vn2000_Datum.h"
#include <cstring>
#include <cmath>
#include <cstdio>

// Portable RTCM datum decoder and the same LLH/NEh/local-LLH chain as Python.
namespace {
constexpr double WGS84_A = 6378137.0;
constexpr double WGS84_B = 6356752.3142;
constexpr double WGS84_E2 = 1.0 - (WGS84_B * WGS84_B) / (WGS84_A * WGS84_A);
constexpr double ARCSEC_TO_RAD = 3.14159265358979323846 / (180.0 * 3600.0);

struct EcefCoordinate {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

EcefCoordinate llhToEcef(double latitudeDeg, double longitudeDeg, double height) {
    const double latitude = latitudeDeg * 3.14159265358979323846 / 180.0;
    const double longitude = longitudeDeg * 3.14159265358979323846 / 180.0;
    const double sinLatitude = sin(latitude);
    const double cosLatitude = cos(latitude);
    const double radius = WGS84_A / sqrt(1.0 - WGS84_E2 * sinLatitude * sinLatitude);
    return {
        (radius + height) * cosLatitude * cos(longitude),
        (radius + height) * cosLatitude * sin(longitude),
        (radius * (1.0 - WGS84_E2) + height) * sinLatitude,
    };
}

void ecefToLlh(const EcefCoordinate &coordinate, double &latitudeRad,
               double &longitudeRad, double &height) {
    const double ep2 = (WGS84_A * WGS84_A - WGS84_B * WGS84_B)
        / (WGS84_B * WGS84_B);
    const double p = sqrt(coordinate.x * coordinate.x + coordinate.y * coordinate.y);
    if (p < 1e-12) {
        latitudeRad = copysign(3.14159265358979323846 / 2.0, coordinate.z);
        longitudeRad = 0.0;
        height = fabs(coordinate.z) - WGS84_B;
        return;
    }
    const double theta = atan2(coordinate.z * WGS84_A, p * WGS84_B);
    const double sinTheta = sin(theta);
    const double cosTheta = cos(theta);
    latitudeRad = atan2(
        coordinate.z + ep2 * WGS84_B * sinTheta * sinTheta * sinTheta,
        p - WGS84_E2 * WGS84_A * cosTheta * cosTheta * cosTheta);
    longitudeRad = atan2(coordinate.y, coordinate.x);
    const double sinLatitude = sin(latitudeRad);
    const double radius = WGS84_A / sqrt(1.0 - WGS84_E2 * sinLatitude * sinLatitude);
    height = p / cos(latitudeRad) - radius;
}

struct UtmProjection {
    double centralMeridianRad = 0.0;
    double scale = 1.0;
    double falseEasting = 0.0;
    double falseNorthing = 0.0;
};

void blhToUtm(const UtmProjection &projection, double latitudeRad,
              double longitudeRad, double &northing, double &easting) {
    const double ep2 = WGS84_E2 / (1.0 - WGS84_E2);
    const double sinLatitude = sin(latitudeRad);
    const double cosLatitude = cos(latitudeRad);
    const double tangent = tan(latitudeRad);
    const double radius = WGS84_A / sqrt(1.0 - WGS84_E2 * sinLatitude * sinLatitude);
    const double t = tangent * tangent;
    const double c = ep2 * cosLatitude * cosLatitude;
    const double a = (longitudeRad - projection.centralMeridianRad) * cosLatitude;
    const double e4 = WGS84_E2 * WGS84_E2;
    const double e6 = e4 * WGS84_E2;
    const double meridian = WGS84_A * (
        (1.0 - WGS84_E2 / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0) * latitudeRad
        - (3.0 * WGS84_E2 / 8.0 + 3.0 * e4 / 32.0 + 45.0 * e6 / 1024.0) * sin(2.0 * latitudeRad)
        + (15.0 * e4 / 256.0 + 45.0 * e6 / 1024.0) * sin(4.0 * latitudeRad)
        - (35.0 * e6 / 3072.0) * sin(6.0 * latitudeRad));
    northing = projection.falseNorthing + projection.scale * (meridian + radius * tangent * (
        a * a / 2.0
        + (5.0 - t + 9.0 * c + 4.0 * c * c) * pow(a, 4) / 24.0
        + (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * ep2) * pow(a, 6) / 720.0));
    easting = projection.falseEasting + projection.scale * radius * (
        a + (1.0 - t + c) * pow(a, 3) / 6.0
        + (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * ep2) * pow(a, 5) / 120.0);
}

void utmToBlh(const UtmProjection &projection, double northing,
              double easting, double &latitudeRad, double &longitudeRad) {
    const double ep2 = WGS84_E2 / (1.0 - WGS84_E2);
    const double x = (northing - projection.falseNorthing) / projection.scale;
    const double y = (easting - projection.falseEasting) / projection.scale;
    const double e4 = WGS84_E2 * WGS84_E2;
    const double e6 = e4 * WGS84_E2;
    const double mu = x / (WGS84_A * (1.0 - WGS84_E2 / 4.0
        - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0));
    const double e1 = (1.0 - sqrt(1.0 - WGS84_E2))
        / (1.0 + sqrt(1.0 - WGS84_E2));
    const double j1 = 3.0 * e1 / 2.0 - 27.0 * pow(e1, 3) / 32.0;
    const double j2 = 21.0 * pow(e1, 2) / 16.0 - 55.0 * pow(e1, 4) / 32.0;
    const double j3 = 151.0 * pow(e1, 3) / 96.0;
    const double j4 = 1097.0 * pow(e1, 4) / 512.0;
    const double footpoint = mu + j1 * sin(2.0 * mu) + j2 * sin(4.0 * mu)
        + j3 * sin(6.0 * mu) + j4 * sin(8.0 * mu);
    const double sinFootpoint = sin(footpoint);
    const double cosFootpoint = cos(footpoint);
    const double tangent = tan(footpoint);
    const double c1 = ep2 * cosFootpoint * cosFootpoint;
    const double t1 = tangent * tangent;
    const double radius = WGS84_A / sqrt(1.0 - WGS84_E2 * sinFootpoint * sinFootpoint);
    const double meridianRadius = radius * (1.0 - WGS84_E2)
        / (1.0 - WGS84_E2 * sinFootpoint * sinFootpoint);
    const double d = y / radius;
    latitudeRad = footpoint - (radius * tangent / meridianRadius) * (
        d * d / 2.0
        - (5.0 + 3.0 * t1 + 10.0 * c1 - 4.0 * c1 * c1 - 9.0 * ep2) * pow(d, 4) / 24.0
        + (61.0 + 90.0 * t1 + 298.0 * c1 + 45.0 * t1 * t1
           - 252.0 * ep2 - 3.0 * c1 * c1) * pow(d, 6) / 720.0);
    longitudeRad = projection.centralMeridianRad + (
        d - (1.0 + 2.0 * t1 + c1) * pow(d, 3) / 6.0
        + (5.0 - 2.0 * c1 + 28.0 * t1 - 3.0 * c1 * c1
           + 8.0 * ep2 + 24.0 * t1 * t1) * pow(d, 5) / 120.0) / cosFootpoint;
}

bool transformItrfToVn2000(double latitudeDeg, double longitudeDeg, double height,
                           const Vn2000Datum &datum, Vn2000Result &result) {
    const EcefCoordinate source = llhToEcef(latitudeDeg, longitudeDeg, height);
    const double omega = datum.helmert.rX * ARCSEC_TO_RAD;
    const double phi = datum.helmert.rY * ARCSEC_TO_RAD;
    const double epsilon = datum.helmert.rZ * ARCSEC_TO_RAD;
    const double k = datum.helmert.kT;
    const EcefCoordinate transformed = {
        datum.helmert.dX + k * (source.x + epsilon * source.y - phi * source.z),
        datum.helmert.dY + k * (-epsilon * source.x + source.y + omega * source.z),
        datum.helmert.dZ + k * (phi * source.x - omega * source.y + source.z),
    };

    double latitudeRad = 0.0;
    double longitudeRad = 0.0;
    double transformedHeight = 0.0;
    ecefToLlh(transformed, latitudeRad, longitudeRad, transformedHeight);
    if (datum.messages.has1023) {
        latitudeRad += datum.residuals.resB;
        longitudeRad += datum.residuals.resL;
        transformedHeight += datum.residuals.resH;
    }
    const UtmProjection projection{
        datum.projection.centralMeridianDeg * 3.14159265358979323846 / 180.0,
        datum.projection.scale,
        datum.projection.falseEasting,
        datum.projection.falseNorthing,
    };
    blhToUtm(projection, latitudeRad, longitudeRad, result.north, result.east);
    result.north += datum.residuals.resN;
    result.east += datum.residuals.resE;
    transformedHeight += datum.residuals.resHS;
    result.h = transformedHeight;
    utmToBlh(projection, result.north, result.east, latitudeRad, longitudeRad);

    const EcefCoordinate vn2000 = llhToEcef(
        latitudeRad * 180.0 / 3.14159265358979323846,
        longitudeRad * 180.0 / 3.14159265358979323846,
        transformedHeight);
    const double reverseOmega = -0.00928836 * ARCSEC_TO_RAD;
    const double reversePhi = 0.01975479 * ARCSEC_TO_RAD;
    const double reverseEpsilon = -0.00427372 * ARCSEC_TO_RAD;
    const double reverseK = 1.000000252906278;
    const EcefCoordinate local = {
        -191.90441429 + reverseK * (vn2000.x + reverseEpsilon * vn2000.y - reversePhi * vn2000.z),
        -39.30318279 + reverseK * (-reverseEpsilon * vn2000.x + vn2000.y + reverseOmega * vn2000.z),
        -111.45032835 + reverseK * (reversePhi * vn2000.x - reverseOmega * vn2000.y + vn2000.z),
    };
    ecefToLlh(local, latitudeRad, longitudeRad, result.altitude);
    result.latitude = latitudeRad * 180.0 / 3.14159265358979323846;
    result.longitude = longitudeRad * 180.0 / 3.14159265358979323846;
    return std::isfinite(result.latitude) && std::isfinite(result.longitude) && std::isfinite(result.altitude)
        && -90.0 <= result.latitude && result.latitude <= 90.0
        && -180.0 <= result.longitude && result.longitude <= 180.0;
}

} // namespace

bool transformVn2000(double latitude, double longitude, double altitude,
                     const Vn2000Datum &datum, Vn2000Result &result) {
    if (!datum.messages.has1021 || !std::isfinite(latitude) || !std::isfinite(longitude) || !std::isfinite(altitude)
        || latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180
        || !std::isfinite(datum.projection.centralMeridianDeg) || datum.projection.centralMeridianDeg < 100 || datum.projection.centralMeridianDeg > 112
        || !std::isfinite(datum.projection.scale) || datum.projection.scale < 0.999 || datum.projection.scale > 1.001
        || !std::isfinite(datum.residuals.resN) || !std::isfinite(datum.residuals.resE) || !std::isfinite(datum.residuals.resHS)) return false;
    return transformItrfToVn2000(latitude, longitude, altitude, datum, result)
        && std::isfinite(result.north) && std::isfinite(result.east) && std::isfinite(result.h)
        && result.altitude >= -1000 && result.altitude <= 100000;
}

namespace {
struct Bits {
    const uint8_t *data;
    size_t limit;
    size_t pos = 36;
    bool ok = true;
    uint64_t u(size_t width) {
        if (width > 63 || pos + width > limit) { ok = false; return 0; }
        uint64_t value = 0;
        for (size_t i = 0; i < width; ++i, ++pos) {
            const auto bit = std::to_integer<uint64_t>((std::byte{data[pos / 8]} >> (7 - pos % 8)) & std::byte{1});
            value = (value << 1) | bit;
        }
        return value;
    }
    int64_t s(size_t width) {
        const uint64_t value = u(width);
        return (value & (uint64_t(1) << (width - 1)))
            ? int64_t(value) - int64_t(uint64_t(1) << width) : int64_t(value);
    }
    void skip(size_t width) { if (pos + width > limit) ok = false; else pos += width; }
};
uint32_t crc24q(const uint8_t *bytes, size_t length) {
    uint32_t crc = 0;
    for (size_t i = 0; i < length; ++i) {
        crc ^= uint32_t(bytes[i]) << 16;
        for (int bit = 0; bit < 8; ++bit) crc = (crc << 1) ^ ((crc & 0x800000) ? 0x1864CFB : 0);
    }
    return crc & 0xFFFFFF;
}
}

void Vn2000Session::reset() { datum_ = Vn2000Datum(); size_ = 0; validFrames_ = 0; }

void Vn2000Session::feed(const uint8_t *data, size_t length) {
    for (size_t i = 0; i < length; ++i) {
        frame_[size_++] = data[i];
        while (size_ > 0) {
            if (frame_[0] != 0xD3 || (size_ >= 2 && (std::byte{frame_[1]} & std::byte{0xFC}) != std::byte{})) {
                memmove(frame_.data(), frame_.data() + 1, --size_);
                continue;
            }
            const size_t expected = size_ >= 3
                ? ((std::to_integer<size_t>(std::byte{frame_[1]} & std::byte{0x03}) << 8) | frame_[2]) + 6
                : 3;
            if (size_ >= 3 && expected < 8) {
                memmove(frame_.data(), frame_.data() + 1, --size_);
                continue;
            }
            if (size_ < expected) {
                break;
            }
            const uint32_t actual = (uint32_t(frame_[expected - 3]) << 16)
                | (uint32_t(frame_[expected - 2]) << 8) | frame_[expected - 1];
            if (crc24q(frame_.data(), expected - 3) == actual) {
                ++validFrames_;
                decode(expected);
                size_ -= expected;
                memmove(frame_.data(), frame_.data() + expected, size_);
            } else memmove(frame_.data(), frame_.data() + 1, --size_);
        }
    }
}

void Vn2000Session::decode(size_t length) {
    const unsigned message = (unsigned(frame_[3]) << 4) | std::to_integer<unsigned>(std::byte{frame_[4]} >> 4);
    Bits bits{frame_.data(), (length - 3) * 8};
    Vn2000Datum next = datum_;
    if (message == 1021) {
        ++datum_.messages.count1021;
        const auto sourceName = static_cast<size_t>(bits.u(5)); bits.skip(8 * sourceName);
        const auto targetName = static_cast<size_t>(bits.u(5)); bits.skip(8 * targetName);
        bits.skip(8 + 10 + 5 + 4 + 2 + 19 + 20 + 14 + 14);
        next.helmert.dX = double(bits.s(23)) * 0.001;
        next.helmert.dY = double(bits.s(23)) * 0.001;
        next.helmert.dZ = double(bits.s(23)) * 0.001;
        next.helmert.rX = double(bits.s(32)) * 0.00002;
        next.helmert.rY = double(bits.s(32)) * 0.00002;
        next.helmert.rZ = double(bits.s(32)) * 0.00002;
        next.helmert.kT = 1.0 + double(bits.s(25)) * 1e-11;
        next.messages.has1021 = bits.ok;
    } else if (message == 1023) {
        ++datum_.messages.count1023;
        bits.skip(8 + 1 + 1 + 21 + 22 + 12 + 12);
        const double meanB = double(bits.s(8)) * 0.001;
        const double meanL = double(bits.s(8)) * 0.001;
        const double meanH = double(bits.s(15)) * 0.01;
        double b = 0;
        double l = 0;
        double h = 0;
        // Retain the reference algorithm's central-four residual mean.
        for (int i = 0; i < 16; ++i) {
            const auto db = static_cast<double>(bits.s(9));
            const auto dl = static_cast<double>(bits.s(9));
            const auto dh = static_cast<double>(bits.s(9));
            if (i == 5 || i == 6 || i == 9 || i == 10) { b += db; l += dl; h += dh; }
        }
        next.residuals.resB = (meanB + b * 0.00003 / 4.0) * ARCSEC_TO_RAD;
        next.residuals.resL = (meanL + l * 0.00003 / 4.0) * ARCSEC_TO_RAD;
        next.residuals.resH = -(meanH + h * 0.001 / 4.0);
        next.messages.has1023 = bits.ok;
    } else if (message == 1025) {
        ++datum_.messages.count1025;
        bits.skip(8);
        next.projection.type = static_cast<uint8_t>(bits.u(6));
        const int64_t originLatitude = bits.s(34);
        next.projection.longitudeRaw = bits.s(35);
        next.projection.scaleRaw = static_cast<uint32_t>(bits.u(30));
        next.projection.centralMeridianDeg = double(next.projection.longitudeRaw) * 1.1e-8;
        next.projection.scale = (double(next.projection.scaleRaw) * 0.00001 + 993000.0) * 0.000001;
        next.projection.falseEasting = double(bits.u(36)) * 0.001;
        next.projection.falseNorthing = double(bits.s(35)) * 0.001;
        if (originLatitude != 0 || next.projection.centralMeridianDeg < 100 || next.projection.centralMeridianDeg > 112
            || next.projection.scale < 0.999 || next.projection.scale > 1.001) return;
        next.messages.has1025 = bits.ok;
        next.projection.frameBytes = static_cast<uint16_t>(length);
        for (size_t i = 0; i < length && i < 32; ++i)
            snprintf(next.projection.frameHex.data() + i * 2, 3, "%02x", frame_[i]);
    } else return;
    if (!bits.ok) return;
    next.messages.count1021 = datum_.messages.count1021;
    next.messages.count1023 = datum_.messages.count1023;
    next.messages.count1025 = datum_.messages.count1025;
    datum_ = next;
}
