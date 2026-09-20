'use strict';
// Public reference sites used by the bundled knowledge catalogs.
function openReference(shell,value){
  if(typeof value!=='string')throw new Error('参考资料链接无效');
  const url=new URL(value),host=url.hostname.replace(/^www\./,'');
  if(!['http:','https:'].includes(url.protocol)||url.username||url.password||!['db.yugioh-card.com','roadoftheking.com','masterduelmeta.com','yugiohmeta.com','ygoprodeck.com'].includes(host))throw new Error('参考资料链接不在已核对来源中');
  return shell.openExternal(url.href);
}
module.exports={openReference};
