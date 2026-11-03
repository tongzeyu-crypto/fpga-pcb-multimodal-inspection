// Valid bits live beside tags in BRAM; a reset/invalidate sweeps tags once.
// Final valid beat writes data and tag together; fully retained samples bypass re-lookup.
// Two fill slots per cache; same-line requests merge and aliasing sets serialize.
// AXI's global eight-ID budget remains in g3_axi_fabric. The local token routes
// interleaved/out-of-order returns to a private beat counter. Captured hits and
// returned texels survive replacement; output remains strictly request ordered.
module g3_tex_cache #(parameter integer CACHE_BYTES=65536)(
 input logic clk,rstn,invalidate,input logic in_valid,output logic in_ready,
 input logic [31:0] address[0:7],output logic out_valid,input logic out_ready,
 output logic [31:0] sampled[0:7],
 output g3_pkg::rd_req_t req,input logic req_ready,
 input g3_pkg::rd_rsp_t rsp,output logic rsp_ready,
 output logic error,output logic [63:0] misses,stall_cycles,request_wait,first_return_wait,bank_conflict_wait);
 import g3_pkg::*;
 localparam integer LINES=CACHE_BYTES/128,LW=$clog2(LINES),BW=LW+3,TW=25-LW;
 typedef enum logic [2:0]{IDLE,READ_BANKS,CHECK,MISS_FIRST,MISS_SECOND,FILL_DATA,FILL_TAG,OUTPUT} state_t;
 state_t state;
 logic [TW:0] tags[0:7];logic scrubbing;logic [LW-1:0] scrub_index;
 logic [31:0] transaction_address[0:7];
 logic [31:0] addr[0:7],bank_addr[0:7],bank_data[0:7],retained[0:7];
 logic [31:0] miss_addr,candidate_miss_addr,second_miss_addr,fill_address[0:1];
 logic missing,second_missing,discard_fill;logic [4:0] fill_count[0:1];
 logic [1:0] active,requested;logic chosen,has_request,return_slot;
 wire [31:0] tag_address=fill_address[return_slot];
 logic [7:0] resolved,hit,pending_miss;logic first_found;
 logic [31:0] output_data[0:7],lookup_sampled[0:7];
 logic output_valid,push_output,pop_output;
 // Two input credits isolate upstream readiness from hit/consumer timing.
 logic load_request,lookup_next,lookup_enable;
 logic q_head,q_tail;logic [1:0] q_count;
 logic [31:0] request_fifo[0:1][0:7],pending_address[0:7],lookup_address[0:7];
 wire request_pending=q_count!=0;
 generate for(genvar a=0;a<8;a=a+1)begin
  assign pending_address[a]=request_fifo[q_head][a];
  assign lookup_address[a]=state==READ_BANKS?transaction_address[a]:pending_address[a];
 end endgenerate
 // Speculative reads never modify tags/data. A failed hit or stalled output
 // keeps the next request queued and repeats its read when retirement resumes.
 assign lookup_next=!scrubbing&&request_pending&&(state==IDLE||state==CHECK||state==OUTPUT);
 assign lookup_enable=!scrubbing&&(state==READ_BANKS||lookup_next);
 integer i,b,l,c;logic found;
 logic [BW-1:0] fill_index;
 logic alias_conflict;
 function automatic [LW-1:0] index_of(input logic [31:0] a);
  logic [LW-1:0] high;begin high=a[7+LW+:LW];index_of=a[7+:LW]^{high[LW-5:0],high[LW-1:LW-4]};end
 endfunction
 assign return_slot=rsp.token[0];
 assign fill_index={index_of(fill_address[return_slot]),fill_count[return_slot][3:1]};
 generate for(genvar bank=0;bank<4;bank=bank+1)begin: banks
  wire filling=state==FILL_DATA&&rsp.valid&&rsp_ready&&active[return_slot]&&fill_count[return_slot][0]==(bank>>1)&&!rsp.error;
  wire [BW-1:0] a=filling?fill_index:{index_of(bank_addr[bank*2]),bank_addr[bank*2][6:4]};
  g3_ram_tdp #(.WIDTH(32),.AW(BW)) data_ram(.clk(clk),
   .ena(lookup_enable||filling),.wea(filling),.addra(a),.dina(bank%2?rsp.data[63:32]:rsp.data[31:0]),.douta(bank_data[bank*2]),
   .enb(lookup_enable),.web(1'b0),.addrb({index_of(bank_addr[bank*2+1]),bank_addr[bank*2+1][6:4]}),.dinb(32'b0),.doutb(bank_data[bank*2+1]));
  wire tag_write=state==FILL_DATA&&rsp.valid&&rsp_ready&&rsp.last&&fill_count[return_slot]==15&&active[return_slot]&&requested[return_slot]&&!rsp.token[1]&&!rsp.error&&!discard_fill&&!error&&!invalidate;
  g3_ram_tdp #(.WIDTH(TW+1),.AW(LW)) tag_ram(.clk(clk),
   .ena(scrubbing||lookup_enable||tag_write),.wea(scrubbing||tag_write),.addra(scrubbing?scrub_index:(tag_write?index_of(tag_address):index_of(lookup_address[bank*2]))),
   .dina(scrubbing?{(TW+1){1'b0}}:{1'b1,tag_address[31:7+LW]}),.douta(tags[bank*2]),
   .enb(lookup_enable),.web(1'b0),.addrb(index_of(lookup_address[bank*2+1])),.dinb({(TW+1){1'b0}}),.doutb(tags[bank*2+1]));
 end endgenerate
 always_comb begin
  for(integer ci=0;ci<8;ci=ci+1)begin hit[ci]=!scrubbing&&tags[ci][TW]&&tags[ci][TW-1:0]==addr[ci][31:7+LW];end
  for(b=0;b<4;b=b+1)for(l=0;l<2;l=l+1)begin bank_addr[b*2+l]=0;found=0;
   for(c=0;c<4;c=c+1)if(lookup_address[l*4+c][3:2]==b&&!found)begin bank_addr[b*2+l]=lookup_address[l*4+c];found=1;end
  end
  // Keep the cache-hit path short. Multi-line miss priority selection is
  // performed over registered masks in two separate stages.
  missing=|(~resolved&~hit);first_found=0;candidate_miss_addr=0;
  for(integer ci=0;ci<8;ci=ci+1)if(pending_miss[ci]&&!first_found)begin candidate_miss_addr={transaction_address[ci][31:7],7'b0};first_found=1;end
  alias_conflict=0;second_missing=0;second_miss_addr=0;
  for(integer ci=0;ci<8;ci=ci+1)if(pending_miss[ci]&&transaction_address[ci][31:7]!=fill_address[0][31:7])begin
   if(index_of(transaction_address[ci])==index_of(fill_address[0]))alias_conflict=1;
   else if(!second_missing)begin second_missing=1;second_miss_addr={transaction_address[ci][31:7],7'b0};end
  end
  has_request=|(active&~requested);chosen=!(active[0]&&!requested[0]);
  // Registered output breaks the tag-compare -> downstream-ready chain.
  // The next lookup can start while the completed pair enters the one-pair holding register.
  // A retiring pair may be replaced in the same cycle. Output valid is registered;
  // the paired arithmetic consumer never waits on tag comparison for its valid.
  out_valid=output_valid;pop_output=out_valid&&out_ready;
  push_output=(state==OUTPUT||(state==CHECK&&!missing))&&(!output_valid||pop_output);
  // One pending request cuts tag compare from upstream raster readiness.
  // With two credits, continuous hits can retire and issue a new RAM read every cycle.
  in_ready=!scrubbing&&!invalidate&&q_count<2;
  load_request=!scrubbing&&(state==IDLE||push_output)&&request_pending;
  req='0;req.valid=state==FILL_DATA&&has_request;req.addr=fill_address[chosen];req.beats=16;req.token={1'b0,chosen};
  rsp_ready=state==FILL_DATA;
  for(integer ci=0;ci<8;ci=ci+1)begin lookup_sampled[ci]=(state==CHECK&&!resolved[ci])?bank_data[addr[ci][3:2]*2+(ci>>2)]:retained[ci];sampled[ci]=output_data[ci];end
 end
 // Delay diagnostic events by one cycle; no cache/AXI control depends on them.
 // Complex cross-cache arbitration no longer drives a 64-bit counter enable.
 logic request_wait_event,first_wait_event,conflict_event;
 always_ff @(posedge clk)begin
  if(!rstn)begin request_wait_event<=0;first_wait_event<=0;conflict_event<=0;end
  else begin
   request_wait_event<=state==FILL_DATA&&has_request&&!req_ready;
   first_wait_event<=state==FILL_DATA&&((requested[0]&&active[0]&&fill_count[0]==0)||(requested[1]&&active[1]&&fill_count[1]==0))&&!rsp.valid;
   conflict_event<=state==MISS_SECOND&&alias_conflict;
  end
 end
 always_ff @(posedge clk)begin
  if(!rstn)begin q_head<=0;q_tail<=0;q_count<=0;output_valid<=0;state<=IDLE;scrubbing<=1;scrub_index<=0;error<=0;misses<=0;stall_cycles<=0;active<=0;requested<=0;discard_fill<=0;first_return_wait<=0;request_wait<=0;bank_conflict_wait<=0;end
  else begin
   // Address metadata follows every speculative BRAM read. Miss handling uses
   // its own snapshot, so cache hit reduction does not enable 256 address FFs.
   if(lookup_enable)for(i=0;i<8;i=i+1)addr[i]<=lookup_address[i];
   if(state==CHECK)for(i=0;i<8;i=i+1)transaction_address[i]<=addr[i];
   if(in_valid&&in_ready)begin q_tail<=!q_tail;for(i=0;i<8;i=i+1)request_fifo[q_tail][i]<=address[i];end
   if(load_request)q_head<=!q_head;
   case({in_valid&&in_ready,load_request})
    2'b10:q_count<=q_count+1;2'b01:q_count<=q_count-1;default:begin end
   endcase
   if(pop_output)output_valid<=0;
   if(push_output)output_valid<=1;
   // Valid qualifies the data. Capture while the holding slot is free even
   // on a miss; no invalid word escapes. Tag comparison must not drive 256
   // data-register enables. A stalled valid pair still holds exactly.
   if(!output_valid||pop_output)for(i=0;i<8;i=i+1)output_data[i]<=lookup_sampled[i];
   if(scrubbing)begin scrub_index<=scrub_index+1; if(scrub_index==LINES-1)scrubbing<=0;end
   if(invalidate)begin scrubbing<=1;scrub_index<=0;discard_fill<=state!=IDLE||output_valid||request_pending;error<=state!=IDLE||output_valid||request_pending;q_count<=0;q_head<=0;q_tail<=0;end
   if(state==FILL_DATA||state==FILL_TAG)stall_cycles<=stall_cycles+1;
   if(request_wait_event)request_wait<=request_wait+1;
   if(first_wait_event)first_return_wait<=first_return_wait+1;
   if(conflict_event)bank_conflict_wait<=bank_conflict_wait+1;
   case(state)
    IDLE:begin end
    READ_BANKS:begin state<=CHECK;end
    CHECK:begin
     // Retain known hits across replacement; missing words arrive from the fill path.
     // Preserve the proven hit-qualified enable after physical timing comparison.
     resolved<=resolved|hit;
     for(i=0;i<8;i=i+1)if(!resolved[i]&&hit[i])retained[i]<=bank_data[addr[i][3:2]*2+(i>>2)];
     if(missing)begin pending_miss<=~resolved&~hit;state<=MISS_FIRST;end
     else state<=push_output?IDLE:OUTPUT;
    end
    MISS_FIRST:begin fill_address[0]<=candidate_miss_addr;state<=MISS_SECOND;end
    MISS_SECOND:begin fill_address[1]<=second_miss_addr;fill_count[0]<=0;fill_count[1]<=0;
     active<=second_missing?2'b11:2'b01;requested<=0;state<=FILL_DATA;end
    FILL_DATA:begin
     if(req.valid&&req_ready)begin requested[chosen]<=1;misses<=misses+1;end
     if(rsp.valid)begin
      if(rsp.token[1]||!active[return_slot]||!requested[return_slot])begin error<=1;state<=OUTPUT;end
      else begin
       fill_count[return_slot]<=fill_count[return_slot]+1;
       if(rsp.error||rsp.last!=(fill_count[return_slot]==15))error<=1;
       for(i=0;i<8;i=i+1)if(!resolved[i]&&transaction_address[i][31:7]==fill_address[return_slot][31:7]&&transaction_address[i][6:3]==fill_count[return_slot][3:0])begin
        retained[i]<=transaction_address[i][2]?rsp.data[63:32]:rsp.data[31:0];resolved[i]<=1;
       end
       if(rsp.last)begin active[return_slot]<=0;end
      end
     end else if(active==0)state<=(error||(&resolved))?OUTPUT:READ_BANKS;
    end
    FILL_TAG:begin state<=FILL_DATA;end
    OUTPUT:if(push_output)state<=IDLE;
    default:state<=IDLE;
   endcase
   if(load_request&&!invalidate)begin resolved<=0;discard_fill<=0;state<=CHECK;end
  end
 end
endmodule
