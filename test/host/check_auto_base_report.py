"""Verify result serialization keeps the conversion report and exact strings."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
a=source.index('String BackendAgent::buildAutoBaseResult('); b=source.index('\nbool BackendAgent::completeAutoBaseSetup(',a)
method=source[a:b]
progress=source[source.index('void BackendAgent::setWorkflowProgress('):source.index('bool BackendAgent::startWorkflow(')]
harness=r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t AUTO_BASE_RESULT_SIZE=6144, PROGRESS_DOCUMENT_SIZE=8192;
struct Epoch { long toInt() { return 123; } };
Epoch epochString() { return {}; }
struct BackendAgent {
    String autoBaseProgress_;
    void markStatusDirty() {}
    void setWorkflowProgress(const String &, uint8_t, uint8_t, const String &);
    String buildAutoBaseResult(double,double,double,double,double,double,bool,bool,size_t,
                               const String &,const String &,const String &,double,double,JsonObjectConst);
};
'''
checks=r'''
int main() {
    DynamicJsonDocument report(8192), decoded(4096);
    report["input_coord"]["lat"]="21.084990131093591";
    report["parameters"]["kT"]="1.00000008613";
    report["output_coord"]["lat"]="21.0849901310";
    report["output_coord"]["lon"]="105.7866560000";
    report["output_coord"]["alt"]="-8.0624";
    report["calculated_coord"]["lat"]="21.084990131093591";
    report["receiver_write_completed"]=true;
    report["source"]["mountpoint"]="NTRIP-TEST";
    report["location"]["province_name"]="Hà Nội";
    report["location"]["projection_options"][0]["l0_deg"]=105.0;
    BackendAgent agent;
    const String result=agent.buildAutoBaseResult(21,105,10,21,105,10,true,true,60,
                                                   "rtcm1025","01","Hanoi",105,0.9999,report.as<JsonObjectConst>());
    assert(!deserializeJson(decoded,result));
    assert(decoded["fixed_samples_only"]==true && decoded["sample_count"]==60);
    assert(decoded["averaged_coord"]["lat"]=="21.0849901310");
    assert(decoded["raw_coord"]["lat"]=="21.084990131093591");
    assert(decoded["calculated_coord"]["lat"]=="21.084990131093591");
    assert(decoded["conversion_report"]["parameters"]["kT"]=="1.00000008613");
    assert(decoded["conversion_report"]["input_coord"]["lat"]=="21.084990131093591");
    assert(decoded["conversion_report"]["receiver_write_completed"]==true);
    decoded["source_mountpoint"] = "NTRIP-TEST";
    decoded["auto_applied"] = true;
    decoded["receiver_write_completed"] = true;
    String details; serializeJson(decoded, details);
    agent.setWorkflowProgress("ready_for_review", 4, 4, details);
    decoded.clear(); assert(!deserializeJson(decoded, agent.autoBaseProgress_));
    assert(decoded["phase"] == "ready_for_review");
    assert(decoded["conversion_report"]["location"]["province_name"] == "Hà Nội");
    assert(decoded["conversion_report"]["location"]["projection_options"][0]["l0_deg"] == 105.0);
    assert(decoded["source_mountpoint"] == "NTRIP-TEST");
    bool sawAccepted = false, sawRejected = false;
    for (size_t size = 0; size <= 6500; size += 250) {
        DynamicJsonDocument candidate(8192), output(AUTO_BASE_RESULT_SIZE), progressOutput(PROGRESS_DOCUMENT_SIZE);
        candidate["source"]["mountpoint"] = "NTRIP-TEST";
        candidate["location"]["padding"] = String(std::string(size, 'x'));
        const String value = agent.buildAutoBaseResult(21,105,10,21,105,10,true,true,60,
                                                        "rtcm1025","01","Hanoi",105,0.9999,candidate.as<JsonObjectConst>());
        if (value.isEmpty()) { sawRejected = true; continue; }
        sawAccepted = true;
        assert(!deserializeJson(output, value));
        output["source_mountpoint"] = String("NTRIP-TEST");
        output["auto_applied"] = true;
        output["receiver_write_completed"] = true;
        assert(!output.overflowed());
        String body; serializeJson(output, body);
        agent.setWorkflowProgress("ready_for_review", 4, 4, body);
        assert(!deserializeJson(progressOutput, agent.autoBaseProgress_));
        assert(progressOutput["phase"] == "ready_for_review");
        assert(progressOutput["conversion_report"]["location"]["padding"].as<String>().length() == size);
    }
    assert(sawAccepted && sawRejected);
    report["location"]["extra"] = String(std::string(6500, 'x'));
    const String oversized=agent.buildAutoBaseResult(21,105,10,21,105,10,true,true,60,
                                                      "rtcm1025","01","Hanoi",105,0.9999,report.as<JsonObjectConst>());
    assert(oversized.isEmpty());
}
'''
with tempfile.TemporaryDirectory(prefix='autobase-report-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+method+progress+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: conversion report and numeric precision survive result serialization')
