/****
    This example was extracted from the MECHS port available here: https://cyberwarriorx.com/download/35/?tmstv=1757363152
****/

//  Include
#include    "SGL.H"
#include    "SL_DEF.H"
#include    "SDDRVS.DAT"

// Sound related

#define     SoundMem         0x25a0b000

extern char mechs_map[];
extern char mechs_ton[];
extern char mechs_seq[];
extern Uint32 mapsize;
extern Uint32 tonsize;
extern Uint32 seqsize;

int Initialize_Sound_System(void)
{
   // Load music

   slInitSound(sddrvstsk, sizeof(sddrvstsk), (Uint8 *)mechs_map, mapsize);

   // SEQ data
   slDMACopy(mechs_seq, (void *)(SoundMem) + 0x21fdc, seqsize);

   // TON data
   slDMACopy(mechs_ton, (void *)(SoundMem) + 0x2737c, tonsize);

   return(1);
} 



//  Functions
int main(void)
{
    /*
        Main Program
        
        Game starts here
    */
    
    //  Initialize Systems 
    slInitSystem(TV_320x224, NULL, 1);
    Initialize_Sound_System();
    slBGMTempo(0);
    slBGMOn((1 << 8) + 0,0,127,0) ;
   
    //  Start Main Game Loop
	while(1)
	{
	    //  Hello World
      slPrint("Example: Playing SEQ files", slLocate(9,2));
      slSynch();
	}
    
    //  End Program
	return 0;
}
