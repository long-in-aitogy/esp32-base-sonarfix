"""Test full baud scan and receiver boot retry using real GNSS identification code."""
from pathlib import Path
import re
import tempfile
from host_coverage import compile_cpp, run_cpp, mapped

root=Path(__file__).resolve().parents[2]
source_path=root/'src/functions/gnss/Gnss_Detection.cpp'
source=re.sub(r'^#include.*$','',source_path.read_text(),flags=re.M)
harness=r'''
#include <Arduino.h>
#include "functions/gnss/gnss_cmd_builder.h"
#include "functions/gnss/Unicore_Identification.h"
#include <cassert>
#include <deque>
#include <vector>
constexpr unsigned GNSS_BAUD=115200;
uint32_t now=0;uint32_t millis(){return now;}void delay(unsigned ms){now+=ms;}
unsigned desiredBaud=38400,asciiCalls=0;int scenario=0;
std::vector<uint8_t> version;
struct {
    unsigned baud=GNSS_BAUD;std::deque<uint8_t> input;
    void updateBaudRate(unsigned value){baud=value;}
    int available(){return input.size();}int read(){auto value=input.front();input.pop_front();return value;}
    size_t write(const uint8_t *data,size_t size){
        if(baud==desiredBaud&&(scenario==1||scenario==3||scenario==4)){
            auto reply=scenario==3?std::vector<uint8_t>(data,data+size):version;
            if(scenario==4)reply.back()^=1;
            input.insert(input.end(),520,0);input.insert(input.end(),reply.begin(),reply.end());
        }return size;
    }
    void print(const char*){
        ++asciiCalls;
        if((scenario==2&&baud==desiredBaud)||(scenario==5&&asciiCalls>=8)){
            const std::string reply="#VERSIONA,UNICORE UM980\r\n";input.insert(input.end(),reply.begin(),reply.end());
        }
    }
    void flush(){}
}Serial1;
'''
checks=r'''
int main(){
    version={0xb5,0x62,10,4,40,0};version.insert(version.end(),40,'A');uint8_t a=0,b=0;
    for(size_t i=2;i<version.size();++i){a+=version[i];b+=a;}version.push_back(a);version.push_back(b);
    for(scenario=0;scenario<=5;++scenario){
        now=0;asciiCalls=0;Serial1.input={1,2,3};desiredBaud=scenario==2?9600:38400;
        const auto actual=detectGnssSensorType();
        const auto expected=scenario==1?GnssCmdBuilder::GnssSensorType::Ublox:
            scenario==2||scenario==5?GnssCmdBuilder::GnssSensorType::Unicore:GnssCmdBuilder::GnssSensorType::Invalid;
        assert(actual==expected&&now>=2000);
        if(expected==GnssCmdBuilder::GnssSensorType::Invalid)assert(Serial1.baud==GNSS_BAUD);
        else if(scenario!=5)assert(Serial1.baud==desiredBaud);
    }
    assert(hasValidUbxFrame(version.data(),version.size()));
    assert(!hasValidUbxFrame(version.data(),version.size()-1));
    auto huge=version;huge[4]=0xff;huge[5]=0xff;assert(!hasValidUbxFrame(huge.data(),huge.size()));
}
'''
with tempfile.TemporaryDirectory(prefix='detection-lifecycle-') as directory:
    path=Path(directory)
    (path/'check.cpp').write_text(harness+mapped(source_path,source,stripped_includes=True)+checks)
    compile_cpp(['c++','-std=c++17','-fsanitize=address,undefined','-I'+str(root/'test/host'),'-I'+str(root/'include'),str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    run_cpp([str(path/'check')],check=True)
print('PASS: complete GNSS baud scan, boot delay/retry, CRC-valid MON-VER, poll rejection, oversize/noise and Unicore identity')
