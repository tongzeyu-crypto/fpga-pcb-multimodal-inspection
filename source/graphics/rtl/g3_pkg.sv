package g3_pkg;
 typedef struct packed {logic valid;logic [31:0] addr;logic [4:0] beats;logic [1:0] token;} rd_req_t;
 typedef struct packed {logic valid,last,error;logic [63:0] data;logic [1:0] token;} rd_rsp_t;
 typedef struct packed {logic valid;logic [31:0] addr;logic [4:0] beats;} wr_req_t;
 typedef struct packed {logic valid;logic [63:0] data;logic [7:0] strb;} wr_data_t;
 function automatic [7:0] div255(input logic [17:0] n);
  logic [18:0] t;begin t=n+128;div255=(t+(t>>8))>>8;end
 endfunction
 function automatic [15:0] sat16(input logic signed [63:0] a);
  begin sat16=a<0?0:a>65535?65535:a[15:0];end
 endfunction
 function automatic [31:0] over(input logic [31:0] dst,src,input logic additive);
  integer c;logic [9:0] t;logic [31:0] o;
  begin o=32'hff000000;for(c=0;c<3;c=c+1)begin
   t=src[c*8+:8]+(additive?dst[c*8+:8]:div255(dst[c*8+:8]*(255-src[31:24])));
   o[c*8+:8]=t>255?255:t[7:0];end over=o;end
 endfunction
endpackage
