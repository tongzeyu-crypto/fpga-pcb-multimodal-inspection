// AXI4 reads: 8 ID-tagged outstanding bursts. Writes: 4 tagged outstanding
// bursts with W data emitted in AW order. Every client sees ordered ownership.
module g3_axi_fabric #(parameter integer NR=5,NW=3)(
 input logic clk,rstn,input g3_pkg::rd_req_t rd[0:NR-1],
 output logic [NR-1:0] rd_ready,output g3_pkg::rd_rsp_t rsp[0:NR-1],input logic [NR-1:0] rsp_ready,
 input g3_pkg::wr_req_t wr[0:NW-1],output logic [NW-1:0] wr_ready,
 input g3_pkg::wr_data_t wd[0:NW-1],output logic [NW-1:0] wd_ready,wr_done,wr_error,
 output logic fault,quiescent,output logic [63:0] read_bytes,write_bytes,wait_cycles,
 output logic [2:0] m_axi_arid,output logic [31:0] m_axi_araddr,
 output logic [7:0] m_axi_arlen,output logic [2:0] m_axi_arsize,
 output logic [1:0] m_axi_arburst,output logic m_axi_arvalid,input logic m_axi_arready,
 input logic [2:0] m_axi_rid,input logic [63:0] m_axi_rdata,input logic [1:0] m_axi_rresp,
 input logic m_axi_rlast,m_axi_rvalid,output logic m_axi_rready,
 output logic [1:0] m_axi_awid,output logic [31:0] m_axi_awaddr,
 output logic [7:0] m_axi_awlen,output logic [2:0] m_axi_awsize,
 output logic [1:0] m_axi_awburst,output logic m_axi_awvalid,input logic m_axi_awready,
 output logic [63:0] m_axi_wdata,output logic [7:0] m_axi_wstrb,
 output logic m_axi_wlast,m_axi_wvalid,input logic m_axi_wready,
 input logic [1:0] m_axi_bid,m_axi_bresp,input logic m_axi_bvalid,output logic m_axi_bready);
 import g3_pkg::*;
 localparam RW=$clog2(NR),WW=$clog2(NW);
 logic [1:0] local_token[0:7];
 logic [7:0] rused;logic [3:0] wused;
 logic [$clog2(NR)-1:0] rowner[0:7];
 logic [$clog2(NW)-1:0] wowner[0:3];
 logic [4:0] rleft[0:7],wleft[0:3];
 logic [1:0] order[0:3],head,tail;
 logic [2:0] queued;logic [1:0] wtag;
 integer rslot,wslot,i,j,k;
 logic [RW-1:0] rround,rchoose;logic [WW-1:0] wround,wchoose;
 logic [NR-1:0] rbits,rmask,religible,rgrant;logic [NW-1:0] wbits,wmask,weligible,wgrant;
 logic rfree,wfree,aw_push,w_pop;
 rd_req_t read_stage;wr_req_t write_stage;
 logic [2:0] read_stage_tag;logic [1:0] write_stage_tag;
 logic [7:0] rissued;logic [3:0] wissued;
 // Two registered return slots separate the external RID lookup/error check
 // from all clients' payload enables. Capture ownership before an ID is reused.
 // Full dequeue/enqueue advances the old back to front and places the new beat in back.
 // A register at the queue head avoids the asynchronous RAM/head multiplexer
 // on every consumer path. Client selection is decoded once on AXI capture.
 rd_rsp_t return_front,return_back,return_capture;
 logic [NR-1:0] return_front_select,return_back_select,return_capture_select;
 logic return_push,return_pop;logic [1:0] return_count;
 generate for(genvar g=0;g<NR;g=g+1)begin: read_grants
  if(g==0)assign rgrant[g]=religible[g];else assign rgrant[g]=religible[g]&&!(|religible[g-1:0]);
 end
 for(genvar g=0;g<NW;g=g+1)begin: write_grants
  if(g==0)assign wgrant[g]=weligible[g];else assign wgrant[g]=weligible[g]&&!(|weligible[g-1:0]);
 end endgenerate
 function automatic [3:0] pop8(input logic [7:0] a);
  integer n;begin pop8=0;for(n=0;n<8;n=n+1)pop8=pop8+a[n];end
 endfunction
 always_comb begin
  quiescent=return_count==0&&rused==0&&wused==0&&!read_stage.valid&&!write_stage.valid&&!m_axi_arvalid&&!m_axi_awvalid&&queued==0;
  rslot=0;rfree=0;for(i=0;i<8;i=i+1)if(!rused[i]&&!rfree)begin rslot=i;rfree=1;end
  wslot=0;wfree=0;for(i=0;i<4;i=i+1)if(!wused[i]&&!wfree)begin wslot=i;wfree=1;end
  for(i=0;i<NR;i=i+1)begin rbits[i]=rd[i].valid;rmask[i]=i>=rround;end
  for(i=0;i<NW;i=i+1)begin wbits[i]=wr[i].valid;wmask[i]=i>=wround;end
  religible=(|(rbits&rmask))?rbits&rmask:rbits;weligible=(|(wbits&wmask))?wbits&wmask:wbits;
  rchoose=0;wchoose=0;
  for(i=0;i<NR;i=i+1)rchoose=rchoose|(rgrant[i]?RW'(i):RW'(0));
  for(i=0;i<NW;i=i+1)wchoose=wchoose|(wgrant[i]?WW'(i):WW'(0));
  rd_ready=0;wr_ready=0;wd_ready=0;
  if(rfree&&!read_stage.valid&&!fault)rd_ready=rgrant;
  if(wfree&&!write_stage.valid&&!fault)wr_ready=wgrant;
  return_capture='0;return_capture.valid=1;return_capture.data=m_axi_rdata;
  return_capture.last=m_axi_rlast;return_capture.token=local_token[m_axi_rid];
  return_capture.error=m_axi_rresp!=0||m_axi_rlast!=(rleft[m_axi_rid]==1);
  return_capture_select='0;return_capture_select[rowner[m_axi_rid]]=1;
  for(i=0;i<NR;i=i+1)begin
   rsp[i]=return_front; // Payload is don't-care when valid is low.
   rsp[i].valid=return_count!=0&&return_front_select[i];
  end
  return_pop=return_count!=0&&(|(rsp_ready&return_front_select));
  m_axi_rready=(return_count<2||return_pop)&&m_axi_rvalid&&rused[m_axi_rid]&&rissued[m_axi_rid];
  return_push=m_axi_rvalid&&m_axi_rready;
  wtag=order[head];m_axi_wvalid=0;m_axi_wdata=0;m_axi_wstrb=0;m_axi_wlast=0;
  if(queued!=0)begin
   m_axi_wvalid=wd[wowner[wtag]].valid;m_axi_wdata=wd[wowner[wtag]].data;
   m_axi_wstrb=wd[wowner[wtag]].strb;m_axi_wlast=wleft[wtag]==1;
   wd_ready[wowner[wtag]]=m_axi_wready;
  end
  m_axi_arsize=3;m_axi_arburst=1;m_axi_awsize=3;m_axi_awburst=1;m_axi_bready=1;
  aw_push=m_axi_awvalid&&m_axi_awready;w_pop=m_axi_wvalid&&m_axi_wready&&m_axi_wlast;
 end
 always_ff @(posedge clk)begin
  if(!rstn)begin
   rused<=0;wused<=0;rissued<=0;wissued<=0;read_stage.valid<=0;write_stage.valid<=0;m_axi_arvalid<=0;m_axi_awvalid<=0;
   return_count<=0;return_front_select<=0;return_back_select<=0;
   rround<=0;wround<=0;head<=0;tail<=0;queued<=0;fault<=0;
   read_bytes<=0;write_bytes<=0;wait_cycles<=0;wr_done<=0;wr_error<=0;
  end else begin
   wr_done<=0;wr_error<=0;
   case({return_push,return_pop})
    2'b10:return_count<=return_count+1;2'b01:return_count<=return_count-1;default:begin end
   endcase
   if(return_pop&&return_count==2)begin
    return_front<=return_back;return_front_select<=return_back_select;
   end
   if(return_push)begin
    if(return_count==0||(return_pop&&return_count==1))begin
     return_front<=return_capture;return_front_select<=return_capture_select;
    end else begin return_back<=return_capture;return_back_select<=return_capture_select;end
   end
   if((m_axi_arvalid&&!m_axi_arready)||(m_axi_awvalid&&!m_axi_awready)||
    (m_axi_wvalid&&!m_axi_wready)||(m_axi_rvalid&&!m_axi_rready))wait_cycles<=wait_cycles+1;
   if(m_axi_arvalid&&m_axi_arready)begin m_axi_arvalid<=0;rissued[m_axi_arid]<=1;end
   if(|rd_ready)begin
    read_stage<=rd[rchoose];read_stage_tag<=rslot;
    rused[rslot]<=1;local_token[rslot]<=rd[rchoose].token;rowner[rslot]<=rchoose;rleft[rslot]<=rd[rchoose].beats;
    rround<=rchoose==NR-1?RW'(0):rchoose+RW'(1);
   end
   if(read_stage.valid&&(!m_axi_arvalid||m_axi_arready)&&!fault)begin
    read_stage.valid<=0;
    if(!read_stage.beats||read_stage.beats>16||read_stage.addr[2:0]!=0||
     ({1'b0,read_stage.addr[11:0]}+({8'b0,read_stage.beats}<<3))>4096)fault<=1;
    else begin
     m_axi_arid<=read_stage_tag;m_axi_araddr<=read_stage.addr;m_axi_arlen<=read_stage.beats-1;m_axi_arvalid<=1;
    end
   end
   if(m_axi_rvalid&&m_axi_rready)begin
    read_bytes<=read_bytes+8;rleft[m_axi_rid]<=rleft[m_axi_rid]-1;
    if(m_axi_rlast)begin rused[m_axi_rid]<=0;rissued[m_axi_rid]<=0;end
    if(m_axi_rresp!=0||m_axi_rlast!=(rleft[m_axi_rid]==1))fault<=1;
   end
   if(m_axi_rvalid&&(!rused[m_axi_rid]||!rissued[m_axi_rid]))fault<=1;
   if(m_axi_awvalid&&m_axi_awready)begin
    m_axi_awvalid<=0;order[tail]<=m_axi_awid;tail<=tail+1;wissued[m_axi_awid]<=1;
   end
   if(|wr_ready)begin
    write_stage<=wr[wchoose];write_stage_tag<=wslot;
    wused[wslot]<=1;wowner[wslot]<=wchoose;wleft[wslot]<=wr[wchoose].beats;
    wround<=wchoose==NW-1?WW'(0):wchoose+WW'(1);
   end
   if(write_stage.valid&&(!m_axi_awvalid||m_axi_awready)&&!fault)begin
    write_stage.valid<=0;
    if(!write_stage.beats||write_stage.beats>16||write_stage.addr[2:0]!=0||
     ({1'b0,write_stage.addr[11:0]}+({8'b0,write_stage.beats}<<3))>4096)fault<=1;
    else begin
     m_axi_awid<=write_stage_tag;m_axi_awaddr<=write_stage.addr;m_axi_awlen<=write_stage.beats-1;m_axi_awvalid<=1;
    end
   end
   case({aw_push,w_pop})2'b10:queued<=queued+1;2'b01:queued<=queued-1;default:begin end endcase
   if(m_axi_wvalid&&m_axi_wready)begin
    write_bytes<=write_bytes+pop8(m_axi_wstrb);wleft[wtag]<=wleft[wtag]-1;
    if(w_pop)head<=head+1;
   end
   if(m_axi_bvalid)begin
    if(!wused[m_axi_bid]||!wissued[m_axi_bid]||wleft[m_axi_bid]!=0)fault<=1;
    else begin
     wr_done[wowner[m_axi_bid]]<=1;wr_error[wowner[m_axi_bid]]<=m_axi_bresp!=0;
     wused[m_axi_bid]<=0;wissued[m_axi_bid]<=0;if(m_axi_bresp!=0)fault<=1;
    end
   end
  end
 end
endmodule
