(function(){
  var iframe = document.createElement('iframe');
  iframe.src = window.UPH_CHATBOT_URL || 'https://staging-chatbot.your-hospital.local';
  iframe.style.position = 'fixed';
  iframe.style.right = '24px';
  iframe.style.bottom = '24px';
  iframe.style.width = '380px';
  iframe.style.height = '680px';
  iframe.style.border = '0';
  iframe.style.zIndex = '99999';
  iframe.style.borderRadius = '16px';
  iframe.style.boxShadow = '0 10px 30px rgba(0,0,0,0.18)';
  document.body.appendChild(iframe);
})();
