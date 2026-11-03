// Small, exclusive-open MMIO driver. Kernel owns resource bounds and mapping.
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/miscdevice.h>
#include <linux/of.h>
#include <linux/of_device.h>
#include <linux/mm.h>
#include <linux/fs.h>
#include <linux/atomic.h>
#include <linux/clk.h>
struct pcb_dev {struct miscdevice misc;resource_size_t start,size;atomic_t opened;};
static int pcb_open(struct inode*i,struct file*f){struct pcb_dev*d=container_of(f->private_data,struct pcb_dev,misc);if(atomic_cmpxchg(&d->opened,0,1))return -EBUSY;return 0;}
static int pcb_close(struct inode*i,struct file*f){struct pcb_dev*d=container_of(f->private_data,struct pcb_dev,misc);atomic_set(&d->opened,0);return 0;}
static int pcb_mmap(struct file*f,struct vm_area_struct*v){struct pcb_dev*d=container_of(f->private_data,struct pcb_dev,misc);unsigned long size=v->vm_end-v->vm_start;if(v->vm_pgoff||!size||size>d->size)return -EINVAL;v->vm_page_prot=pgprot_noncached(v->vm_page_prot);v->vm_flags|=VM_IO|VM_DONTEXPAND|VM_DONTDUMP;return remap_pfn_range(v,v->vm_start,d->start>>PAGE_SHIFT,size,v->vm_page_prot);}
static const struct file_operations pcb_ops={.owner=THIS_MODULE,.open=pcb_open,.release=pcb_close,.mmap=pcb_mmap,.llseek=no_llseek};
static void pcb_clock_off(void *clock){clk_disable_unprepare(clock);}
static int pcb_probe(struct platform_device*p){struct resource*r=platform_get_resource(p,IORESOURCE_MEM,0);struct pcb_dev*d;struct clk *clock;int rc;if(!r)return -ENODEV;d=devm_kzalloc(&p->dev,sizeof(*d),GFP_KERNEL);if(!d)return -ENOMEM;
 clock=devm_clk_get_optional(&p->dev,"aclk");
 if(IS_ERR(clock))return PTR_ERR(clock);
 rc=clk_prepare_enable(clock);if(rc)return rc;
 rc=devm_add_action_or_reset(&p->dev,pcb_clock_off,clock);if(rc)return rc;
 if(!devm_request_mem_region(&p->dev,r->start,resource_size(r),dev_name(&p->dev)))
  return -EBUSY;
 d->start=r->start;
 d->size=resource_size(r);
 atomic_set(&d->opened,0);
 d->misc.minor=MISC_DYNAMIC_MINOR;
 d->misc.name=(const char*)of_device_get_match_data(&p->dev);
 d->misc.fops=&pcb_ops;
 d->misc.parent=&p->dev;
 rc=misc_register(&d->misc);
 if(!rc)platform_set_drvdata(p,d);
 return rc;
}
static int pcb_remove(struct platform_device*p){struct pcb_dev*d=platform_get_drvdata(p);if(atomic_read(&d->opened))return -EBUSY;misc_deregister(&d->misc);return 0;}
static const struct of_device_id pcb_match[]={{.compatible="pcb,ai-1",.data="pcb_ai"},{.compatible="pcb,adc-1",.data="pcb_adc"},{.compatible="pcb,adc-2",.data="pcb_adc"},{.compatible="pcb,demo-1",.data="pcb_demo"},{}};
MODULE_DEVICE_TABLE(of,pcb_match);
static struct platform_driver pcb_driver={.probe=pcb_probe,.remove=pcb_remove,.driver={.name="pcb-compute",.of_match_table=pcb_match,.suppress_bind_attrs=true}};
module_platform_driver(pcb_driver);
MODULE_LICENSE("GPL");MODULE_DESCRIPTION("PCB AI ADC and signal image MMIO resource driver");
