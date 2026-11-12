"""Verify result serialization keeps the conversion report and exact strings."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
a=source.index('String BackendAgent::buildAutoBaseResult('); b=source.index('\nbool BackendAgent::completeAutoBaseSetup(',a)
method=source[a:b]
harness=r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE=4096;
struct BackendAgent {
    String buildAutoBaseResult(double,double,double,double,double,double,bool,bool,size_t,
                               const String &,const String &,const String &,double,double,JsonObjectConst);
};
'''
checks=r'''
int main() {
    DynamicJsonDocument report(2048), decoded(4096);
    report["input_coord"]["lat"]="21.084990131093591";
    report["parameters"]["kT"]="1.00000008613";
    report["output_coord"]["lat"]="21.0849901310";
    report["output_coord"]["lon"]="105.7866560000";
    report["output_coord"]["alt"]="-8.0624";
    report["calculated_coord"]["lat"]="21.084990131093591";
    report["receiver_write_completed"]=true;
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
}
'''
with tempfile.TemporaryDirectory(prefix='autobase-report-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: conversion report and numeric precision survive result serialization')
