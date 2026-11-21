/* A complete C99 caller of the same prebuilt model SDK. */
#include "qwen3_tts.h"
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static volatile sig_atomic_t stopped;
static void stop(int sig) { stopped = sig; }
static void u16(unsigned char *p, uint16_t n) {p[0]=(unsigned char)n;p[1]=(unsigned char)(n>>8);}
static void u32(unsigned char *p, uint32_t n) {u16(p,(uint16_t)n);u16(p+2,(uint16_t)(n>>16));}
static int header(FILE *f, uint32_t rate, uint32_t bytes) {
    unsigned char h[44]={0};
    memcpy(h,"RIFF",4);u32(h+4,36+bytes);memcpy(h+8,"WAVEfmt ",8);
    u32(h+16,16);u16(h+20,1);u16(h+22,1);u32(h+24,rate);
    u32(h+28,rate*2);u16(h+32,2);u16(h+34,16);memcpy(h+36,"data",4);u32(h+40,bytes);
    return fseek(f,0,SEEK_SET)==0 && fwrite(h,1,sizeof(h),f)==sizeof(h);
}
int main(int argc,char **argv) {
    q3t_engine *e=NULL; q3t_info info; q3t_request req; q3t_stats stats;
    float *audio=NULL; unsigned char *pcm=NULL; FILE *file=NULL;
    uint32_t bytes=0;int result=1,n,rc;const char *output;
    if(argc<3 || argc>5){fprintf(stderr,"Usage: %s MODELS OUTPUT.wav [zh|en] [TEXT]\n",argv[0]);return 2;}
    int zh=argc>=4 && strcmp(argv[3],"zh")==0;
    if(argc>=4 && !zh && strcmp(argv[3],"en")!=0){fputs("Choose zh or en\n",stderr);return 2;}
    output=argv[2];
    if(signal(SIGINT,stop)==SIG_ERR || signal(SIGTERM,stop)==SIG_ERR){perror("signal");return 1;}
    rc=q3t_create_with_runtime(argv[1],NULL,NULL,&e);
    if(rc<0){fprintf(stderr,"Load: %s (%d)\n",q3t_create_error(),rc);goto done;}
    if(stopped){result=128+stopped;goto done;}
    if(q3t_get_info(e,&info)<0)goto native_error;
    if(info.max_chunk_samples<=0 || (size_t)info.max_chunk_samples>SIZE_MAX/sizeof(float) || info.sampling_rate<=0 || info.sampling_rate>INT_MAX/2){fputs("Invalid model audio sizes\n",stderr);goto done;}
    audio=malloc((size_t)info.max_chunk_samples*sizeof(float));pcm=malloc((size_t)info.max_chunk_samples*2);
    if(!audio || !pcm){fputs("Allocation failed\n",stderr);goto done;}
    file=fopen(output,"wb");if(!file){perror("output");goto done;}
    if(!header(file,(uint32_t)info.sampling_rate,0)){perror("WAV header");goto done;}
    q3t_default_request(&req);req.speaker=zh?"vivian":"ryan";req.language=zh?"chinese":"english";
    req.text=argc==5?argv[4]:(zh?"你好，欢迎使用语音合成。今天，我们用清晰自然的声音，把文字变成可以听见的表达。":"Hello, welcome to text-to-speech. Today, we use a clear and natural voice to turn written words into speech you can hear.");
    if(q3t_start(e,&req)<0)goto native_error;
    while(!stopped && (n=q3t_next_audio(e,audio,info.max_chunk_samples))>0){
        if(n>info.max_chunk_samples || (uint64_t)bytes+(uint64_t)n*2>UINT32_MAX-36){fputs("WAV size exceeded\n",stderr);goto done;}
        for(int i=0;i<n;i++){
            float x=audio[i];if(!isfinite(x)){fputs("Invalid audio\n",stderr);goto done;}
            if(x>1)x=1;
            if(x<-1)x=-1;
            int16_t sample=(int16_t)(x*32767.0f);u16(pcm+2*(size_t)i,(uint16_t)sample);
        }
        size_t count=(size_t)n*2;if(fwrite(pcm,1,count,file)!=count){perror("audio write");goto done;}
        bytes+=(uint32_t)count;
    }
    if(stopped){if(q3t_cancel(e)<0)goto native_error;result=128+stopped;}
    else if(n<0)goto native_error;
    else {if(q3t_get_stats(e,&stats)<0)goto native_error;printf("%s: %.2fs, end_reason=%d\n",output,(double)bytes/2/info.sampling_rate,stats.end_reason);result=0;}
    if(!header(file,(uint32_t)info.sampling_rate,bytes)){perror("final WAV header");result=1;}
    goto done;
native_error:
    fprintf(stderr,"Inference: %s\n",q3t_last_error(e));
done:
    if(file && fclose(file)!=0){perror("close output");result=1;}
    free(audio);free(pcm);
    rc=q3t_destroy_owned(&e);if(rc<0){fprintf(stderr,"Cleanup failed (%d)\n",rc);result=1;}
    if(result==1 && file)remove(output);
    return result;
}
