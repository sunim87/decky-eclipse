export const staticClasses = { Title: 'title' };
export const PanelSection = ({ title, children }: any) => <section><h2>{title}</h2>{children}</section>;
export const PanelSectionRow = ({ children }: any) => <div>{children}</div>;
export const ButtonItem = ({ children, disabled, onClick, description }: any) =>
  <div><button disabled={disabled} onClick={onClick}>{children}</button>{description && <small>{description}</small>}</div>;
export const TextField = ({ label, value, onChange }: any) => <input aria-label={label} value={value} onChange={onChange} />;
import { createRoot } from 'react-dom/client';
export const ConfirmModal = ({strTitle,strDescription,strOKButtonText,strCancelButtonText,onOK,onCancel}:any) =>
  <div role="dialog"><h2>{strTitle}</h2>{strDescription}<button onClick={onOK}>{strOKButtonText}</button><button onClick={onCancel}>{strCancelButtonText}</button></div>;
export const showModal = (content:any) => {
  const element=document.createElement('div');document.body.append(element);
  const root=createRoot(element);root.render(content);
  return {Close:()=>{root.unmount();element.remove();},ClosedPromise:Promise.resolve(),Update:(next:any)=>root.render(next)};
};
