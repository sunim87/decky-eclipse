import { definePlugin } from '@decky/api';
import { staticClasses } from '@decky/ui';
import { FaMoon } from 'react-icons/fa';
import { Content } from './Content';

export default definePlugin(() => ({
  name: 'Decky Eclipse',
  titleView: <div className={staticClasses.Title}>Decky Eclipse</div>,
  content: <Content />,
  icon: <FaMoon />,
  onDismount() {},
}));
