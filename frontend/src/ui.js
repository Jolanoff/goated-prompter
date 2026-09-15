// Shared Tailwind recipes. Complete class strings keep Vite's Tailwind scanning
// static; state is expressed with data attributes and native control variants.
// `panel`, `reference-map`, `director-choice` (and App's `selected`) are only
// compatibility hooks for existing browser tests; no stylesheet styles them.
const control = "w-full rounded-lg border border-[#353747] bg-[#11131b] placeholder:text-[#696b80] focus:outline-none focus:border-[#9273ed] focus:shadow-[0_0_0_3px_#9472f212]";
const textarea = `${control} block resize-y px-[15px] py-[14px]`;
const panel = "panel min-w-0 rounded-[11px] border border-[#272936] bg-[linear-gradient(120deg,#181a23_0%,#14161e_100%)] shadow-[0_5px_17px_#00000010]";
const panelPadding = "p-[19px] wide:p-[23px] compact:p-4 mobile:p-[18px] tiny:p-[15px]";
const buttonFrame = "inline-flex items-center justify-center gap-2 min-h-[38px] rounded-[7px] border font-medium whitespace-nowrap enabled:hover:bg-none enabled:hover:bg-[#2c293c] enabled:hover:border-[#7c689f]";
const button = `${buttonFrame} border-[#36394c] bg-[linear-gradient(120deg,#222431,#1a1d28)] px-3 py-[9px] text-[10px] text-[#cecee2]`;
const iconButtonFrame = "inline-flex size-[30px] shrink-0 items-center justify-center rounded-[5px] border-0 bg-transparent text-[#b2abc5]";
const listChoice = "flex flex-col items-start gap-[5px] rounded-lg border border-[#393244] bg-transparent p-3 text-left text-inherit wrap-anywhere data-[active=true]:border-[#aa8cda] data-[active=true]:bg-[#aa8cda18] [&_span]:text-[11px] [&_span]:opacity-70";
const generationButton = `
  flex items-center justify-center gap-[15px] min-h-[73px] rounded-[9px] px-[18px] py-[14px]
  tablet:gap-2.5 tablet:px-2.5 tablet:py-[13px] mobile:min-h-[58px]
  [&_strong]:block [&_strong]:font-display [&_strong]:text-[16px]
  [&_strong]:font-[750] [&_strong]:tracking-[-0.25px] compact:[&_strong]:text-[14px]
  [&_small]:block [&_small]:mt-[5px] [&_small]:font-normal mobile:[&_small]:hidden
`;

export const ui = {
  input: `${control} h-[41px] px-3 py-0 text-[#e6e5ef]`,
  select: `${control} h-[41px] appearance-none pl-3 pr-8 py-0 text-ellipsis text-[#e6e5ef] disabled:opacity-70 [&_option]:bg-[#191b25] [&_option]:px-0.5 [&_option]:pb-px`,
  panel: `${panel} ${panelPadding}`,
  panelHeader: "mb-[17px] flex items-center gap-3 compact:gap-2.5 tablet:gap-2 mobile:gap-[11px]",
  panelIcon: "flex h-[41px] w-[39px] shrink-0 items-center justify-center rounded-[9px] border border-[#aa8bfc26] bg-[linear-gradient(140deg,#9d78f528,#8361ce15)] text-[#b9a1ff] shadow-[inset_0_1px_0_#ffffff05] compact:w-[34px] compact:h-9 mobile:w-[38px] mobile:h-10",
  panelHeading: `
    min-w-0 [&_h2]:font-display [&_h2]:text-[15px] [&_h2]:tracking-[-0.3px] [&_h2]:font-[750]
    wide:[&_h2]:text-[17px] compact:[&_h2]:text-[14px] tablet:[&_h2]:text-[13px]
    mobile:[&_h2]:text-[16px] tiny:[&_h2]:text-[14px]
    [&_p]:mt-1 [&_p]:text-[10px] [&_p]:leading-[1.5] [&_p]:text-[#9799af]
    wide:[&_p]:text-[11px] compact:[&_p]:text-[9px] mobile:[&_p]:text-[10px] tiny:[&_p]:text-[9px]
  `,
  // More specific header variants preserve the title sizes of these two panels.
  ideaPanel: "[&>header_h2]:text-[19px] wide:[&>header_h2]:text-[21px] compact:[&>header_h2]:text-[14px] tablet:[&>header_h2]:text-[17px] mobile:[&>header_h2]:text-[19px] tiny:[&>header_h2]:text-[14px]",
  outputPanel: "[&>header]:gap-2.5 compact:[&>header_p]:max-w-[195px] mobile:[&>header_p]:max-w-none",
  sidebar: "fixed inset-y-0 left-0 z-10 flex w-[205px] flex-col overflow-y-auto border-r border-line bg-[linear-gradient(160deg,#14161f,#101218_65%,#1a1728)] compact:w-[175px] tablet:w-[72px] mobile:static mobile:h-auto mobile:w-auto mobile:flex-row mobile:flex-wrap mobile:items-center mobile:border-r-0 mobile:border-b mobile:bg-none mobile:bg-[#13151d] mobile:px-[17px] tiny:px-3 [&_nav]:grid [&_nav]:gap-2 [&_nav]:px-[11px] tablet:[&_nav]:px-[9px] tablet:[&_nav]:py-[18px] mobile:[&_nav]:flex mobile:[&_nav]:w-full mobile:[&_nav]:overflow-x-auto mobile:[&_nav]:pb-2 mobile:[&_nav]:px-0 mobile:[&_nav]:pt-0",
  sidebarBrand: "flex h-[110px] items-center gap-2.5 px-5 font-display text-[17px] font-extrabold tracking-[2px] compact:px-4 compact:text-[14px] compact:gap-[7px] compact:[&>svg]:w-[42px] tablet:justify-center tablet:p-0 tablet:h-[86px] tablet:[&>span]:hidden mobile:h-[58px] mobile:justify-start mobile:[&>svg]:size-[33px]",
  brandSub: "mt-[3px] block text-[9px] font-medium tracking-[3.6px] text-[#a4a0ba] compact:text-[8px] compact:tracking-[2.5px] mobile:text-[6px]",
  navCaption: "mx-[23px] my-[18px] text-[9px] tracking-[2px] text-[#6f7187] tablet:hidden",
  navItem: `
    relative flex items-center gap-[11px] rounded-[7px] border border-transparent bg-transparent
    px-3 py-[15px] text-left text-[12px] font-medium whitespace-nowrap text-[#a9abc0]
    [&:hover:not([data-active=true])]:bg-[#ffffff05] [&:hover:not([data-active=true])]:text-white
    data-[active=true]:bg-[linear-gradient(90deg,#7c5adc29,#8d70e314)]
    data-[active=true]:text-[#d7c9ff] data-[active=true]:border-[#9a78f315]
    data-[active=true]:before:absolute data-[active=true]:before:h-6 data-[active=true]:before:w-[3px]
    data-[active=true]:before:bg-[#a388fa] data-[active=true]:before:-left-3
    data-[active=true]:before:rounded-r data-[active=true]:before:content-['']
    compact:text-[10px] compact:gap-2 compact:px-[9px] compact:py-[13px]
    tablet:text-[0px] tablet:p-[13px] tablet:justify-center tablet:gap-0
    tablet:data-[active=true]:before:-left-2.5 mobile:text-[10px] mobile:gap-1.5 mobile:p-2.5
    mobile:[&_svg]:w-[15px] mobile:data-[active=true]:before:hidden
  `,
  navCount: "ml-auto min-w-5 rounded bg-[#ffffff09] p-0.5 text-center text-[10px] compact:text-[9px] compact:min-w-[17px] tablet:hidden",
  sidebarBottom: "relative mt-auto px-[23px] pt-[90px] pb-40 compact:px-[18px] tablet:hidden [&_p]:mt-[18px] [&_p]:font-display [&_p]:text-[18px] [&_p]:leading-[1.65] [&_p]:font-semibold [&_p]:tracking-[-0.6px] compact:[&_p]:text-[17px] [&_p_span]:text-[#8c83a1]",
  localLabel: "flex items-center gap-[7px] text-[8px] tracking-[1.2px] whitespace-nowrap text-[#9490a6] compact:text-[7px] compact:tracking-[0.7px] [&>span]:size-[5px]",
  mainShell: "ml-[205px] flex min-h-screen flex-col compact:ml-[175px] tablet:ml-[72px] mobile:ml-0",
  topbar: "flex min-h-[86px] items-center justify-between gap-5 border-b border-line bg-[#11131bdd] px-[30px] py-[18px] wide:px-10 compact:px-[22px] compact:py-[17px] mobile:min-h-[73px] mobile:px-[18px] mobile:py-[13px] mobile:gap-2.5 tiny:px-[13px]",
  headerTitle: "flex items-center gap-[13px] [&>svg]:hidden [&_h1]:font-display [&_h1]:text-[21px] [&_h1]:font-extrabold [&_h1]:tracking-[-0.5px] tablet:[&_h1]:text-[19px] mobile:[&_h1]:text-[17px] tiny:[&_h1]:text-[15px] [&_p]:mt-1 [&_p]:text-[11px] [&_p]:text-muted mobile:[&_p]:text-[10px]",
  connectionPill: "flex items-center gap-2 rounded-md border border-[#3b655038] bg-[#18352a25] px-[11px] py-[9px] text-[10px] text-[#8be7b4] data-[offline=true]:text-[#cfac82] data-[offline=true]:border-[#765336] data-[offline=true]:[&>span]:bg-[#d6a06a] mobile:text-[8px] mobile:p-2 mobile:gap-1.5 tiny:text-[7px]",
  statusDot: "inline-block size-[7px] shrink-0 rounded-full bg-success",
  localOnly: "flex items-center gap-[7px] text-[8px] tracking-[1.2px] text-[#89899d] [&_svg]:text-[#c0afd8] compact:hidden",
  main: "mx-auto w-full max-w-[1600px] flex-1 px-[30px] pt-[30px] pb-[25px] wide:px-10 wide:pt-[38px] wide:pb-7 compact:px-[22px] compact:py-[25px] mobile:px-[17px] mobile:py-[23px] tiny:px-3 tiny:py-5 data-[builder=true]:pb-[124px] mobile:data-[builder=true]:pb-[100px]",
  builderSave: "mb-4 flex flex-wrap items-center gap-3 text-[12px] text-muted [&_[role=alert]]:text-[#f0bcba]",
  pageHeading: "mb-[26px] flex items-center justify-between gap-5 mobile:mb-[21px] [&_h2]:font-display [&_h2]:text-[25px] [&_h2]:font-[750] [&_h2]:tracking-[-1px] [&_h2]:leading-[1.4] compact:[&_h2]:text-[23px] tablet:[&_h2]:text-[22px] mobile:[&_h2]:text-[24px] mobile:[&_h2]:max-w-[320px] [&_h2_span]:text-[#b09ce9] [&_p]:mt-[7px] [&_p]:text-[11px] [&_p]:text-muted mobile:[&_p]:text-[10px] mobile:[&_p]:leading-[1.7] mobile:[&>button]:text-[0px] mobile:[&>button]:min-w-9 mobile:[&>button]:p-[9px] mobile:[&>button]:gap-0",
  eyebrow: "mb-2 text-[9px] font-semibold tracking-[1.9px] text-[#90869f] mobile:text-[8px] mobile:tracking-[1.3px]",
  workspaceTag: "flex items-center gap-[7px] pt-[14px] text-[10px] whitespace-nowrap text-[#9190a6] compact:hidden",
  workspaceGrid: "grid grid-cols-[minmax(0,1.37fr)_minmax(0,1fr)] items-start gap-[18px] compact:gap-[15px] compact:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] mobile:grid-cols-1 mobile:gap-4",
  column: "flex min-w-0 flex-col gap-[17px] mobile:gap-4",
  ideaInput: `${textarea} h-[165px] pb-8 text-[12px] leading-[1.7] text-[#e6e5ef] bg-[linear-gradient(120deg,#11131b,#14161f)] wide:h-[184px] mobile:h-[145px]`,
  charCount: "pointer-events-none absolute right-[13px] bottom-[11px] rounded bg-[#13151deb] px-1 py-0.5 text-[9px] text-[#8d90a7]",
  inputHint: "mt-[11px] flex items-center gap-[7px] text-[9px] text-[#73788f] [&_svg]:text-[#aa94d5]",
  fields: "mb-4 grid gap-[14px]",
  threeFields: "grid-cols-[0.85fr_0.95fr_1.4fr] compact:grid-cols-2 compact:[&>label:last-child]:col-span-full mobile:grid-cols-[0.8fr_0.95fr_1.35fr] mobile:[&>label:last-child]:col-auto tiny:grid-cols-2 tiny:[&>label:last-child]:col-span-full",
  field: "flex min-w-0 flex-col gap-2 text-[11px] wide:text-[12px] [&>span:first-child]:text-[#d8d8e4] [&>span:first-child]:font-medium [&_input]:text-[11px] [&_select]:text-[11px] wide:[&_input]:text-[12px] wide:[&_select]:text-[12px] mobile:[&_input]:text-[11px] mobile:[&_select]:text-[11px]",
  selectWrap: "relative block min-w-0 [&>svg]:pointer-events-none [&>svg]:absolute [&>svg]:right-3 [&>svg]:top-1/2 [&>svg]:-translate-y-1/2 [&>svg]:text-[#a4a2bd]",
  directorDescription: "mt-[7px] block text-[10px] leading-[1.6] text-[#83869d]",
  resultStatus: "ml-auto flex items-center gap-1.5 rounded-[5px] bg-[#74d99b09] px-2 py-[7px] text-[9px] whitespace-nowrap text-[#89dba9] [&>span]:size-[5px] data-[working=true]:text-accent data-[working=true]:bg-[#a38bed0a] data-[working=true]:[&>span]:bg-accent compact:text-[8px] compact:p-[5px] tiny:text-[7px]",
  outputInput: `${textarea} min-h-[231px] pb-[35px] font-code text-[11px] text-[#bdc0d4] leading-[1.85] wide:min-h-[258px] compact:min-h-[200px] tablet:min-h-[320px] mobile:min-h-[240px]`,
  outputActions: "mt-3 grid grid-cols-[1fr_1fr_0.7fr] gap-[9px] compact:gap-1.5 compact:[&>button]:px-1.5 compact:[&>button]:py-[9px] compact:[&>button]:text-[9px] compact:[&>button]:gap-[5px] mobile:[&>button]:text-[10px] mobile:[&>button]:px-2 mobile:[&>button]:py-2.5 mobile:[&>button]:gap-[7px]",
  button,
  saveButton: `${buttonFrame} px-3 py-[9px] text-[10px] text-[#cbbbfa] border-[#73609060] bg-[#9673ff0a]`,
  primaryButton: `${buttonFrame} mt-2 bg-[linear-gradient(110deg,#936eea,#7953cb)] text-white border-[#a689e0] px-5 py-[11px] text-[12px]`,
  toggleRow: "relative flex min-w-0 cursor-pointer items-center gap-2.5 compact:gap-[7px] [&_small]:mt-[3px] [&_small]:block [&_small]:text-[8px] [&_small]:leading-[1.6] [&_small]:text-[#9190a6] compact:[&_small]:text-[7px] tablet:[&_small]:text-[9px] mobile:[&_small]:text-[8px] tiny:[&_small]:text-[7px]",
  toggleInput: "peer absolute inset-0 z-[1] m-0 h-full w-full cursor-pointer opacity-0",
  switch: `
    relative h-5 w-[33px] shrink-0 rounded-[20px] border border-[#454457] bg-[#303140]
    transition-[background] duration-200 after:absolute after:left-0.5 after:top-0.5
    after:size-[14px] after:rounded-full after:bg-[#acacc0] after:shadow-[0_1px_4px_#0004]
    after:transition-[translate,background] after:duration-200 after:content-['']
    compact:h-[18px] compact:w-[29px] compact:after:size-3
    peer-checked:bg-[linear-gradient(100deg,#7957e8,#a889fa)] peer-checked:border-[#ab90f5]
    peer-checked:shadow-[0_0_10px_#7957e815] peer-checked:after:translate-x-[13px]
    peer-checked:after:bg-[#f8f5ff] compact:peer-checked:after:translate-x-[11px]
    peer-focus-visible:outline-2 peer-focus-visible:outline-[#c6afff] peer-focus-visible:outline-offset-[3px]
    peer-disabled:opacity-50 peer-disabled:cursor-not-allowed
  `,
  toggleLabel: "block text-[10px] font-medium text-[#dedbe9] tablet:text-[11px] mobile:text-[10px]",
  countChip: "ml-auto rounded-[5px] border border-[#33303f] px-[7px] py-1 text-[10px] whitespace-nowrap text-[#a7a1bc]",
  imageSlot: "relative h-[157px] overflow-hidden rounded-lg border border-dashed border-[#706185] bg-[linear-gradient(140deg,#25202f40,#15161f)] hover:border-[#b398f7] hover:bg-none hover:bg-[#a785f609] data-[image=true]:border-solid data-[image=true]:border-[#484055] wide:h-[180px] tablet:h-[145px] mobile:h-[180px] tiny:h-[155px] [&_img]:size-full [&_img]:object-cover",
  uploadLabel: "relative flex size-full cursor-pointer flex-col items-center justify-center gap-[7px] p-2 text-center focus-within:outline-2 focus-within:outline-accent focus-within:-outline-offset-4 [&_input]:absolute [&_input]:inset-0 [&_input]:size-full [&_input]:opacity-0 [&_input]:cursor-pointer [&_strong]:text-[11px] [&_strong]:font-medium [&_strong]:text-[#e0dcec] [&>span:last-of-type]:text-[9px] [&>span:last-of-type]:text-[#9b95ae] tablet:[&>span:last-of-type]:text-[8px] tiny:[&>span:last-of-type]:text-[7px] [&_small]:text-[8px] [&_small]:tracking-[0.5px] [&_small]:text-[#777189]",
  imageRemove: "absolute top-[7px] right-[7px] flex rounded-[5px] border border-[#ffffff25] bg-[#101019cc] p-1",
  imageCaption: "absolute inset-x-0 bottom-0 grid gap-[3px] bg-[linear-gradient(transparent,#090a11ec)] px-[9px] pt-[22px] pb-2 [&>span:first-child]:text-[8px] [&>span:first-child]:font-bold [&>span:first-child]:tracking-[1px] [&>span:last-child]:truncate [&>span:last-child]:text-[8px] [&>span:last-child]:text-[#bdb8ce]",
  referenceMap: "reference-map mt-[13px] grid grid-cols-1 gap-x-[17px] gap-y-[7px] compact:gap-x-2.5 mobile:gap-x-[17px] mobile:gap-y-[9px] tiny:gap-x-2.5",
  referenceRow: "flex items-center justify-between gap-1.5 py-1 text-[11px] text-[#acaec1] [&>span:last-child]:w-[120px] [&>span:last-child]:shrink-0 [&_select]:h-9 [&_select]:rounded-[5px] [&_select]:text-[11px] [&_select]:pl-2 [&_select]:pr-5 [&_select]:border-[#2d2f3e] [&_select]:bg-[#11131a80] [&>span>svg]:right-1.5",
  subtleNote: "mt-3 text-[9px] leading-[1.7] text-[#808399]",
  notesInput: `${textarea} h-[108px] font-notes text-[10px] text-[#e6e5ef] leading-[1.9] wide:h-[122px] tablet:h-[115px] mobile:h-[110px]`,
  directorInput: `${textarea} h-[250px] min-h-[340px] font-notes text-[10px] text-[#e6e5ef] leading-[1.8]`,
  inlineActions: "mt-[11px] flex flex-wrap gap-2",
  settingsForm: "max-w-[850px] [&_label:has(input[type=checkbox])]:mt-[22px] [&_button[type=submit]]:mt-0",
  textButton: "inline-flex items-center gap-1.5 border-0 bg-none p-0 text-[9px] text-[#b4a4d9] enabled:hover:text-[#e1d6ff]",
  warningNote: "mt-2.5 border-l-2 border-[#987444] bg-[#a97c3010] px-[11px] py-[9px] text-[10px] leading-[1.6] text-[#c6b598] wrap-anywhere",
  generationBar: "fixed inset-x-0 bottom-0 left-[205px] z-40 m-0 grid grid-cols-[1.7fr_1fr] gap-[13px] border-t border-[#343548] bg-[#10121aeb] px-[max(30px,calc((100vw-1805px)/2+30px))] py-3 shadow-[0_-12px_36px_#05060a80] backdrop-blur-[16px] compact:grid-cols-[1.35fr_1fr] tablet:left-[72px] tablet:px-[22px] tablet:grid-cols-[1.3fr_1fr] mobile:left-0 mobile:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] mobile:gap-2 mobile:px-3 mobile:pt-[9px] mobile:pb-[calc(9px+env(safe-area-inset-bottom))]",
  generateButton: `${generationButton} border border-[#b497ff] bg-[linear-gradient(110deg,#9976f3,#7950e9_80%)] shadow-[inset_0_1px_0_#ffffff30,0_5px_24px_#7144db25] text-white enabled:hover:bg-[linear-gradient(110deg,#a787fa,#8a65ed)] enabled:hover:shadow-[0_5px_25px_#7144db45] disabled:opacity-70 [&_small]:text-[10px] [&_small]:text-[#e1d6ff] compact:[&_small]:text-[9px] mobile:[&_strong]:text-[13px]`,
  endButton: `${generationButton} border border-[#744b52] bg-[linear-gradient(110deg,#402329,#2c1c20)] text-[#f0b5bd] shadow-[inset_0_1px_0_#ffffff06] disabled:opacity-50 enabled:hover:bg-none enabled:hover:bg-[#512d34] enabled:hover:border-[#b96c78] [&_small]:text-[9px] [&_small]:text-[#c99ba2] compact:[&_small]:text-[8px] tablet:[&_small]:max-w-[155px] tablet:[&_small]:leading-[1.5] mobile:[&_strong]:text-[11px] mobile:[&_svg]:w-[18px]`,
  belowActions: "mt-3 flex flex-wrap items-center gap-[14px] text-[9px] text-[#71748a] mobile:gap-3 mobile:text-[8px] [&>span:first-child]:mr-auto [&>span:first-child]:flex [&>span:first-child]:items-center [&>span:first-child]:gap-[5px]",
  previewNote: "text-[8px] mobile:w-full mobile:text-right mobile:-mt-[5px]",
  message: "mb-[18px] flex items-center gap-3 rounded-lg border border-[#a6535366] bg-[#402125] px-4 py-[13px] text-[12px] leading-[1.6] text-[#f0bcba] [&>span]:flex-1",
  retryButton: "rounded-[5px] border border-[#b2746e] bg-[#6d3b3b] px-2.5 py-1.5 text-[10px]",
  iconButton: `${iconButtonFrame} hover:bg-[#ffffff09] hover:text-[#eeeeee]`,
  deleteButton: `${iconButtonFrame} ml-auto hover:text-[#edabab] hover:bg-[#d75d5d15]`,
  toastRegion: "pointer-events-none fixed bottom-6 left-[calc(50%+100px)] z-30 max-w-[90vw] -translate-x-1/2 compact:left-[calc(50%+87px)] tablet:left-[calc(50%+36px)] mobile:left-1/2 mobile:w-max data-[builder=true]:bottom-28 mobile:data-[builder=true]:bottom-[calc(91px+env(safe-area-inset-bottom))]",
  toast: "flex items-center gap-[9px] rounded-lg border border-[#706083] bg-[#282333] px-5 py-[13px] text-[12px] leading-[1.6] text-[#e0d4f5] shadow-[0_10px_40px_#0006] [&_svg]:text-[#94dbaa] mobile:text-[11px] mobile:px-[15px] mobile:py-3",
  emptyState: "flex min-h-[440px] flex-col items-center justify-center gap-[18px] rounded-xl border border-dashed border-[#34303f] bg-[radial-gradient(ellipse_at_50%_50%,#9571e10b,transparent_70%)] p-[30px] text-center mobile:min-h-[360px] [&_h2]:font-display [&_h2]:text-[23px] [&_h2]:font-bold [&_h2]:tracking-[-0.7px] [&_h3]:font-display [&_h3]:text-[23px] [&_h3]:font-bold [&_h3]:tracking-[-0.7px] mobile:[&_h2]:text-[21px] mobile:[&_h3]:text-[21px] [&_p]:text-[12px] [&_p]:leading-[1.8] [&_p]:text-[#8c8ba2]",
  emptyIcon: "grid size-[70px] place-items-center rounded-[18px] border border-[#5d4c782f] bg-[#a578f20c] text-[#a58bd1]",
  savedCard: `${panel} p-[23px] compact:p-4 mobile:p-[18px] tiny:p-[15px] [&_h3]:mt-4 [&_h3]:font-display [&_h3]:text-[17px] [&_h3]:font-bold [&_h3]:leading-[1.5] [&_h3]:wrap-anywhere mobile:[&_h3]:text-[18px] [&_pre]:font-notes [&_pre]:text-[11px] [&_pre]:text-[#a3a4ba] [&_pre]:whitespace-pre-wrap [&_pre]:wrap-anywhere [&_pre]:leading-[1.85] [&_pre]:max-h-[230px] [&_pre]:min-h-[100px] [&_pre]:overflow-auto [&_pre]:py-1.5 [&_pre]:mt-[14px] [&_pre]:mb-5 mobile:[&_pre]:text-[12px]`,
  savedMeta: "flex items-center justify-between gap-2.5 text-[9px] text-[#7f8098] [&>span]:px-[7px] [&>span]:py-[5px] [&>span]:bg-[#a17ae515] [&>span]:text-[#bfa6e3] [&>span]:border [&>span]:border-[#9d72e121] [&>span]:rounded",
  dialog: "m-auto w-[420px] max-w-[calc(100vw-32px)] rounded-[15px] border border-[#514360] bg-[linear-gradient(130deg,#211e2d,#171720)] p-7 text-[#eee9f7] shadow-[0_25px_100px_#0009] backdrop:bg-[#06060bbd] backdrop:backdrop-blur-[5px] [&_h2]:font-display [&_h2]:text-[25px] [&_h2]:font-bold [&_h2]:tracking-[-0.7px] [&_p]:mt-2.5 [&_p]:mb-[22px] [&_p]:text-[12px] [&_p]:leading-[1.7] [&_p]:text-[#a19ab3] [&_form>button:last-child]:w-full [&_form>button:last-child]:mt-5",
  directorsGrid: "grid grid-cols-[minmax(220px,1fr)_minmax(0,2fr)] gap-6 [&>*]:min-w-0 [&_fieldset]:min-w-0 [&_label]:mb-4 [@media(width<=760px)]:grid-cols-1",
  directorList: "mb-5 grid max-h-[58vh] gap-2 overflow-y-auto overscroll-contain pr-1.5 [scrollbar-width:thin] [scrollbar-color:#65577a_#171923]",
  directorChoice: `director-choice ${listChoice}`,
  versionChoice: listChoice,
};
